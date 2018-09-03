# -*- coding: utf-8 -*-
# Copyright (c) 2018, openetech.com and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import add_months, today, date_diff, getdate, add_days, flt

class SubscriptionBilling(Document):
	def validate(self):
		if self.start_date >= self.end_date:
			frappe.throw(_("Start Date cannot be greater than End Date"))

	def create_sales_entries(self):
		booking_start_date = getdate(add_months(today(), -1))
		booking_start_date = booking_start_date if booking_start_date > self.start_date else self.start_date

		booking_end_date = getdate(add_days(today(), -1))

		if booking_end_date >= self.end_date:
			booking_end_date = self.end_date

		total_days = date_diff(self.end_date, self.start_date)
		total_booking_days = date_diff(booking_end_date, booking_start_date) + 1
		base_amount = flt(self.rate * self.qty * total_booking_days/flt(total_days)) * 12

		event_doc = frappe.new_doc("Subscription Billing Events")
		event_doc.subscription_billing = self.name
		event_doc.event_date = booking_end_date
		event_doc.qty = self.qty
		event_doc.billed_amount = base_amount
		event_doc.insert(ignore_permissions=True)

		if base_amount > 0:
			si_doc = frappe.new_doc('Sales Invoice')
			si_doc.company = self.company
			si_doc.currency = frappe.db.get_value("Company", self.company, "default_currency")
			si_doc.customer = self.customer
			si_doc.posting_date = booking_end_date
			si_doc.due_date = booking_end_date
			si_doc.append("items", {
				"item_code": self.item,
				"qty": self.qty,
				"rate": base_amount / self.qty
			})
			si_doc.set_missing_values()
			si_doc.sei_sub_id = self.name
			si_doc.flags.ignore_mandatory = True
			si_doc.insert(ignore_permissions=True)

	def create_billing_from_events(self):
		sub_events = frappe.db.sql('''select name, event_date, qty
						from `tabSubscription Billing Events` 
						where subscription_billing = %s and event_date<=%s and event_date>=%s
						and billed_amount = 0
						order by event_date asc''', (self.name, today(), add_months(today(), -1)),as_dict=1)
	
		booking_start_date = getdate(add_months(today(), -1))
		booking_start_date = booking_start_date if booking_start_date > self.start_date else self.start_date

		booking_end_date = getdate(add_days(today(), -1))

		if booking_end_date >= self.end_date:
			booking_end_date = self.end_date

		total_days = date_diff(self.end_date, self.start_date)

		max_count = len(sub_events)
		count = 0
		base_amount = 0
		#validation in events doc type that new event date being entered is greater than previous end date
		events = []
		event_name = ''
		for sub_dict in sub_events:
			event_name = sub_dict["name"]
			count += 1
			if count == 1:
				calc_amount = 0
				total_booking_days = date_diff(sub_dict["event_date"], booking_start_date)
				calc_amount = flt(self.rate * self.qty * total_booking_days/flt(total_days)) * 12
				base_amount += calc_amount
				events.append({
						'start_date': booking_start_date,
						'end_date': sub_dict["event_date"],
						'qty': self.qty,
						'rate': calc_amount / self.qty
						})
			else:
				calc_amount = 0
				total_booking_days = date_diff(sub_dict["event_date"], last_event_end_date)
				calc_amount = flt(self.rate * last_event_qty * total_booking_days/flt(total_days)) * 12
				base_amount += calc_amount
				events.append({
						'start_date': last_event_end_date,
						'end_date': sub_dict["event_date"],
						'qty': last_event_qty,
						'rate': calc_amount / last_event_qty
						})
			last_event_end_date = sub_dict["event_date"]
			last_event_qty = sub_dict["qty"]

		last_event_amount = 0
		count = 0
		for sub_dict in sub_events:
			count += 1
			if count == max_count:
				calc_amount = 0
				total_booking_days = date_diff(booking_end_date, sub_dict["event_date"])
				calc_amount = flt(self.rate * sub_dict["qty"] * total_booking_days/flt(total_days)) * 12
				last_event_amount += calc_amount
				events.append({
						'start_date': sub_dict["event_date"],
						'end_date': booking_end_date,
						'qty': sub_dict["qty"],
						'rate': calc_amount / sub_dict["qty"]
						})

		if base_amount > 0:
			si_doc = frappe.new_doc('Sales Invoice')
			si_doc.company = self.company
			si_doc.currency = frappe.db.get_value("Company", self.company, "default_currency")
			si_doc.customer = self.customer
			si_doc.posting_date = booking_end_date
			si_doc.due_date = booking_end_date
			for event in events:
				si_doc.append("items", {
								"item_code": self.item,
								"qty": event['qty'],
								"rate": event['rate'],
								"service_start_date": event['start_date'],
								"service_end_date": event['end_date']
							})
			si_doc.set_missing_values()
			si_doc.flags.ignore_mandatory = True
			si_doc.insert(ignore_permissions=True)

			event_doc = frappe.get_doc("Subscription Billing Events", event_name)
			event_doc.billed_amount = base_amount
			event_doc.save()

def create_sales_invoice():

	subs = frappe.db.sql_list('''
								select name 
								from `tabSubscription Billing` 
								where start_date<=%s and end_date>=%s
								and name not in (select subscription_billing 
												from `tabSubscription Billing Events`
												where billed_amount > 0
												and event_date <= %s and event_date >= %s)''',
						(today(), add_months(today(), -1),today(), add_months(today(), -1)))

	for sub_billing in subs:
		sub_events = frappe.db.sql_list('''select name
						from `tabSubscription Billing Events` 
						where subscription_billing = %s and event_date<=%s and event_date>=%s
						and billed_amount = 0''', (sub_billing, today(), add_months(today(), -1)))
		if sub_events:
			doc = frappe.get_doc("Subscription Billing", sub_billing)
			doc.create_billing_from_events()
		else:
			doc = frappe.get_doc("Subscription Billing", sub_billing)
			doc.create_sales_entries()
