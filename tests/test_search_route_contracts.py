"""Unified search returns every supported active entity category."""

from datetime import date
from decimal import Decimal

from app.models.contacts import Customer, Vendor
from app.models.estimates import Estimate, EstimateStatus
from app.models.invoices import Invoice, InvoiceStatus
from app.models.items import Item, ItemType
from app.models.payments import Payment


def test_unified_search_all_categories_and_empty(client, db_session):
    customer = Customer(name="Needle Customer", is_active=True)
    vendor = Vendor(name="Needle Vendor", is_active=True)
    item = Item(name="Needle Item", item_type=ItemType.SERVICE, is_active=True)
    db_session.add_all([customer, vendor, item])
    db_session.flush()
    invoice = Invoice(
        invoice_number="NEEDLE-INV",
        customer_id=customer.id,
        date=date(2026, 9, 8),
        status=InvoiceStatus.SENT,
        total=Decimal("10"),
        amount_paid=Decimal("0"),
        balance_due=Decimal("10"),
    )
    estimate = Estimate(
        estimate_number="NEEDLE-EST",
        customer_id=customer.id,
        date=date(2026, 9, 8),
        status=EstimateStatus.PENDING,
        total=Decimal("20"),
    )
    payment = Payment(
        customer_id=customer.id,
        date=date(2026, 9, 8),
        amount=Decimal("5"),
        reference="NEEDLE-PAY",
        method="check",
    )
    db_session.add_all([invoice, estimate, payment])
    db_session.commit()

    response = client.get("/api/search?q=Needle")
    assert response.status_code == 200
    assert set(response.json()) == {
        "customers",
        "vendors",
        "items",
        "invoices",
        "estimates",
        "payments",
    }
    assert response.json()["customers"][0]["name"] == "Needle Customer"
    assert client.get("/api/search?q=Absent").json() == {}
    assert client.get("/api/search?q=x").status_code == 422
