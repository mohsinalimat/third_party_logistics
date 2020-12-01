# Copyright (c) 2013, GreyCube Technologies and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import getdate, add_days


def execute(filters=None):
    columns, data = get_columns(filters), get_data(filters)
    return columns, data

def get_columns(filters):
    return [
		dict(label=_("SO#"), fieldname="name", fieldtype="Link/Stock Entry", width=160),
		dict(label=_("Customer"), fieldname="customer_cf", width=200),
		dict(label=_("Date"), fieldname="posting_date", width=120),
		dict(label=_("Received as Pallet/LC"), fieldname="received_as_cf", width=140),
		dict(label=_("No of Pallet/LC"), fieldname="pallet_lc_qty", width=120),
		dict(label=_("Container Type"), fieldname="container_type_cf", width=140),
		dict(label=_("Total Receiving Charge"), fieldname="total_receiving_charge", width=120),
		dict(label=_("Invoiced"), fieldname="invoiced_cf", fieldtype="Check", width=80),
    ]

def get_data(filters):
    where_clause = get_conditions(filters)
    where_clause = " and ste.customer_cf = %(customer)s"

    from third_party_logistics.third_party_logistics.billing.billing_controller import get_carton_container_receiving_charge
    receiving_carton_item = frappe.db.get_value("Third Party Logistics Settings", None, "receiving_carton_item")
    receiving_pallet_item = frappe.db.get_value("Third Party Logistics Settings", None, "receiving_pallet_item")
    carton_container_charges = get_carton_container_receiving_charge(filters["customer"], filters["company"], receiving_carton_item)

    data = frappe.db.sql("""
    select
        name, customer_cf, posting_date,  received_as_cf, 
        pallet_qty_cf, loose_cartons_qty_cf, container_type_cf, 
        coalesce(nullif(pallet_qty_cf,0),loose_cartons_qty_cf) pallet_lc_qty,
        0 total_receiving_charge, invoiced_cf
    from
        `tabStock Entry` ste
    where
        ste.docstatus = 1
        and ste.stock_entry_type = 'Material Receipt'
        and ste.posting_date between %(from_date)s and %(to_date)s
        and ste.customer_cf is not null
        and (pallet_qty_cf+loose_cartons_qty_cf) > 0
        {where_clause}
        order by ste.posting_date, posting_time
    """.format(where_clause=where_clause), filters, as_dict=True)

    if not data:
        return []

    invoice = frappe.new_doc('Sales Invoice')
    invoice.set_posting_time = 1
    invoice.posting_date = getdate()
    invoice.customer = filters["customer"]
    invoice.company = filters["company"]
    invoice.due_date = add_days(getdate(), 30)
    # using a different naming series so that it doesn't interfere with regular invoice sequence
    invoice.naming_series = 'TPL-SINV-'

    for d in data:
            if d.received_as_cf == "Loose Cartons":
                if carton_container_charges.get(d.container_type_cf, 0) > (carton_container_charges.get(receiving_carton_item, 0) * d.loose_cartons_qty_cf):
                    invoice.append("items", {
                        "item_code": d.container_type_cf,
                        "qty": 1,
                        "description": d.name
                    })
                else:
                    invoice.append("items", {
                        "item_code": receiving_carton_item,
                        "qty": d.loose_cartons_qty_cf,
                        "description": d.name

                    })
            elif d.received_as_cf == "Pallet":
                invoice.append("items", {
                    "item_code": receiving_pallet_item,
                    "qty": d.pallet_qty_cf,
                    "description": d.name
                })
    invoice.set_missing_values(for_validate=True)
    invoice.save(ignore_permissions=True)

    for d in invoice.items:
        for stock_entry in [x for x in data if x.name == d.description]:
            stock_entry.total_receiving_charge = d.amount
    invoice.delete()
    return data

def get_conditions(filters):
    where_clause = []
    if filters.get("customer"):
        where_clause = where_clause + ["customer_cf = %(customer)s"]

    return where_clause and " and " + " and ".join(where_clause) or ""
