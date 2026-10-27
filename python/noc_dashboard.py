"""Print a text summary of SLA data from the configured MySQL database."""

from sla_form_backend import get_dashboard_summary, list_inquiries


def display_dashboard_summary():
    summary, audits = get_dashboard_summary()
    inquiries = list_inquiries()

    print("=" * 96)
    print("RAMA COMPUTER & NETWORK SOLUTION - NOC DASHBOARD")
    print("=" * 96)
    print(
        "Total inquiries: {total_inquiries} | Pending audits: {pending_audits} | "
        "Active contracts: {active_contracts} | Gold tier: {gold_clients}".format(
            **summary
        )
    )
    print("-" * 96)
    print(
        "{:<24} | {:<25} | {:<12} | {:<18} | {}".format(
            "REFERENCE", "COMPANY", "TIER", "SUB-CITY", "STATUS"
        )
    )
    print("-" * 96)

    for inquiry in inquiries:
        print(
            "{:<24} | {:<25} | {:<12} | {:<18} | {}".format(
                inquiry["inquiry_ref"][:24],
                inquiry["company_name"][:25],
                inquiry["tier_name"][:12],
                inquiry["sub_city"][:18],
                inquiry["inquiry_status"],
            )
        )

    print("-" * 96)
    print("Upcoming audit visits: {}".format(len(audits)))
    for audit in audits:
        print(
            "{} {} | {} | {} | {}".format(
                audit["audit_date"],
                audit["audit_time"],
                audit["inquiry_ref"],
                audit["company_name"],
                audit["assigned_engineer_name"],
            )
        )


if __name__ == "__main__":
    display_dashboard_summary()
