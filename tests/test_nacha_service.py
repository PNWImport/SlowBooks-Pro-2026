"""Synthetic ACH record totals and deposit allocations; no bank transmission."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace as Obj

import pytest

from app.models.bank_accounts import (
    EmployeeBankAccount,
    BankAccountKind,
    DepositType,
    PrenoteStatus,
)
from app.models.payroll import Employee, PayRun, PayRunStatus, PayStub
from app.services import nacha_export as nacha
from app.services.encryption import encrypt

ORIGIN = {
    "immediate_destination": "021000021",
    "immediate_origin": "123456789",
    "originating_dfi_id": "02100002",
    "company_id": "1234567890",
    "company_name": "Synthetic Company",
    "company_account": "123456789",
    "destination_name": "Synthetic Bank",
    "origin_name": "Synthetic Company",
}


def account(kind, value=0, priority=0):
    return Obj(deposit_type=kind, deposit_value=Decimal(str(value)), priority=priority)


@pytest.mark.parametrize(
    "accounts,amounts",
    [
        ([account(DepositType.FULL)], ["100.01"]),
        (
            [account(DepositType.FIXED, 30), account(DepositType.REMAINDER)],
            ["30", "70.01"],
        ),
        (
            [account(DepositType.PERCENT, 33), account(DepositType.REMAINDER)],
            ["33", "67.01"],
        ),
        ([account(DepositType.FIXED, 200)], ["100.01"]),
        ([account("unknown"), account(DepositType.FULL)], ["100.01"]),
        (
            [
                account(DepositType.REMAINDER, priority=-1),
                account(DepositType.FIXED, 25),
            ],
            ["25", "75.01"],
        ),
    ],
)
def test_split_deposits_conserve_every_cent(accounts, amounts):
    allocations = nacha._split_net_pay(Decimal("100.01"), accounts)
    assert [amount for _, amount in allocations] == list(map(Decimal, amounts))
    assert sum(amount for _, amount in allocations) == Decimal("100.01")


def test_underallocation_is_rejected():
    with pytest.raises(ValueError, match="unallocated"):
        nacha._split_net_pay(Decimal("100"), [account(DepositType.FIXED, 20)])
    assert nacha._split_net_pay(Decimal("0"), [account(DepositType.FULL)]) == []


def test_fixed_width_helpers():
    assert nacha._num("12345", 3) == "345"
    assert nacha._num("a1", 3) == "001"
    assert nacha._alpha("abcdef", 3) == "abc"
    assert nacha._alpha(None, 3) == "   "
    assert nacha._cents(Decimal("1.005")) == 101
    assert nacha._routing_prefix(None) == "00000000"
    assert nacha._check_digit(None) == "0"
    assert nacha.validate_routing_number("021000021")
    assert not nacha.validate_routing_number("021000022")
    assert not nacha.validate_routing_number("bad")


@pytest.fixture
def payroll(db_session):
    employee = Employee(first_name="Synthetic", last_name="Employee")
    unbanked = Employee(first_name="Check", last_name="Only")
    day = date(2026, 1, 15)
    run = PayRun(
        period_start=day, period_end=day, pay_date=day, status=PayRunStatus.PROCESSED
    )
    db_session.add_all([employee, unbanked, run])
    db_session.flush()
    db_session.add_all(
        [
            PayStub(
                pay_run_id=run.id, employee_id=employee.id, net_pay=Decimal("100.01")
            ),
            PayStub(pay_run_id=run.id, employee_id=unbanked.id, net_pay=50),
        ]
    )
    banks = []
    for kind, deposit, value in [
        (BankAccountKind.CHECKING, DepositType.FIXED, 30),
        (BankAccountKind.SAVINGS, DepositType.REMAINDER, 0),
    ]:
        bank = EmployeeBankAccount(
            employee_id=employee.id,
            account_kind=kind,
            deposit_type=deposit,
            deposit_value=value,
            routing_number_enc=encrypt("021000021"),
            account_number_enc=encrypt("123456789"),
            is_active=True,
            prenote_status=PrenoteStatus.CONFIRMED,
        )
        db_session.add(bank)
        banks.append(bank)
    db_session.commit()
    return run, banks


def assert_structure(text):
    lines = text.splitlines()
    assert len(lines) % 10 == 0
    assert all(len(line) == 94 for line in lines)
    assert lines[0][0] == "1" and lines[1][0] == "5"
    return lines


def test_payroll_file_balances_credits_and_offset(db_session, payroll):
    run, _ = payroll
    lines = assert_structure(nacha.generate_nacha_file(db_session, run.id, ORIGIN))
    entries = [line for line in lines if line.startswith("6")]
    assert [line[1:3] for line in entries] == ["22", "32", "27"]
    assert [int(line[29:39]) for line in entries] == [3000, 7001, 10001]
    assert [int(line[-7:]) for line in entries] == [1, 2, 3]
    control = next(line for line in lines if line.startswith("8"))
    assert int(control[4:10]) == 3
    assert int(control[10:20]) == 3 * 2100002
    assert int(control[20:32]) == int(control[32:44]) == 10001
    file_control = next(
        line for line in lines if line.startswith("9") and line != "9" * 94
    )
    assert int(file_control[7:13]) == len(lines) // 10
    assert int(file_control[13:21]) == 3
    assert int(file_control[31:43]) == int(file_control[43:55]) == 10001


def test_missing_and_unprocessed_runs_fail(db_session, payroll):
    with pytest.raises(ValueError, match="not found"):
        nacha.generate_nacha_file(db_session, -1, ORIGIN)
    run, _ = payroll
    run.status = PayRunStatus.DRAFT
    db_session.commit()
    with pytest.raises(ValueError, match="not processed"):
        nacha.generate_nacha_file(db_session, run.id, ORIGIN)


def test_pending_and_inactive_accounts_are_not_credited(db_session, payroll):
    run, banks = payroll
    banks[0].is_active = False
    banks[1].prenote_status = PrenoteStatus.PENDING
    db_session.commit()
    # An ACH file with zero entries is refused, not returned as a valid file.
    with pytest.raises(ValueError, match="direct-deposit details"):
        nacha.generate_nacha_file(db_session, run.id, ORIGIN)


def test_prenotes_have_zero_amount_and_correct_account_codes(db_session, payroll):
    _, banks = payroll
    lines = assert_structure(
        nacha.generate_prenote_file(db_session, [b.id for b in banks], ORIGIN)
    )
    entries = [line for line in lines if line.startswith("6")]
    assert [line[1:3] for line in entries] == ["23", "33"]
    assert all(int(line[29:39]) == 0 for line in entries)
    assert not any(
        line.startswith("6")
        for line in assert_structure(
            nacha.generate_prenote_file(db_session, [], ORIGIN)
        )
    )


def test_legacy_orphan_stub_is_not_paid(db_session, payroll):
    run, _ = payroll
    # SQLite legacy files may predate foreign-key enforcement.
    db_session.add(PayStub(pay_run_id=run.id, employee_id=999999, net_pay=500))
    db_session.commit()
    lines = assert_structure(nacha.generate_nacha_file(db_session, run.id, ORIGIN))
    assert len([line for line in lines if line.startswith("6")]) == 3


def test_contractor_missing_draft_and_zero_amount(db_session):
    from app.models.contacts import Vendor
    from app.models.contractor_payments import (
        ContractorPayRun,
        ContractorRunStatus,
        ContractorPayment,
        VendorBankAccount,
    )

    with pytest.raises(ValueError, match="not found"):
        nacha.generate_contractor_nacha_file(db_session, -1, ORIGIN)
    run = ContractorPayRun(pay_date=date.today())
    vendor = Vendor(name="Synthetic vendor")
    db_session.add_all([run, vendor])
    db_session.commit()
    with pytest.raises(ValueError, match="not processed"):
        nacha.generate_contractor_nacha_file(db_session, run.id, ORIGIN)
    run.status = ContractorRunStatus.PROCESSED
    unbanked_vendor = Vendor(name="Unbanked vendor")
    db_session.add_all(
        [
            ContractorPayment(run_id=run.id, vendor_id=vendor.id, amount=0),
            ContractorPayment(run_id=run.id, vendor=unbanked_vendor, amount=9),
            VendorBankAccount(
                vendor_id=vendor.id,
                account_kind=BankAccountKind.SAVINGS,
                routing_number_enc=encrypt("021000021"),
                account_number_enc=encrypt("123456789"),
            ),
        ]
    )
    db_session.commit()
    with pytest.raises(ValueError, match="direct-deposit details"):
        nacha.generate_contractor_nacha_file(db_session, run.id, ORIGIN)

    # A funded savings account emits the vendor credit and company offset.
    run.payments[0].amount = 12.34
    db_session.commit()
    lines = assert_structure(
        nacha.generate_contractor_nacha_file(db_session, run.id, ORIGIN)
    )
    entries = [line for line in lines if line.startswith("6")]
    assert [line[1:3] for line in entries] == ["32", "27"]
    assert [int(line[29:39]) for line in entries] == [1234, 1234]
