# RAMA Computer and Network Solution - Email & SMS Notification Engine

def generate_client_confirmation_email(company_name, contact_person, inquiry_ref, tier_name, response_time, sub_city):
    subject = "RAMA SLA Confirmation: Onboarding Request [{}] - {}".format(
        inquiry_ref, company_name
    )
    
    body = """Dear {contact_person},

Thank you for selecting RAMA Computer and Network Solution for your IT infrastructure maintenance in Addis Ababa.

We have received your enrollment request for the {tier_name} package. Below are your contract initiation details:

--------------------------------------------------------------------------------
SLA INQUIRY REFERENCE: {inquiry_ref}
COMPANY:               {company_name}
FACILITY LOCATION:     {sub_city} Sub-City, Addis Ababa
SELECTED SLA TIER:     {tier_name}
GUARANTEED P1 RESPONSE:{response_time}
--------------------------------------------------------------------------------

NEXT STEPS:
1. Technical Site Assessment: A RAMA senior network engineer (Cisco/MikroTik certified) will visit your facility in {sub_city} to conduct a preliminary Fluke cable certification test and UPS voltage health check.
2. Custom Proposal & Contract Sign-off: Following the site assessment, we will present your final monthly retainer proposal and emergency hotline dispatch contacts.

If you require urgent assistance or immediate dispatch, please contact our NOC hotline at +251 (0) 911-000000 or email noc@ramanetworks.et.

Best regards,

NOC Engineering & Onboarding Team
RAMA Computer and Network Solution
Addis Ababa, Ethiopia
www.ramanetworks.et
""".format(
        contact_person=contact_person,
        tier_name=tier_name,
        inquiry_ref=inquiry_ref,
        company_name=company_name,
        sub_city=sub_city,
        response_time=response_time,
    )
    return {"subject": subject, "body": body}


def generate_engineer_dispatch_sms(inquiry_ref, company_name, sub_city, tier_name, phone_number, priority="P1"):
    sms_text = (
        "🚨 RAMA DISPATCH ALERT [{priority}]: {tier_name} Client "
        "'{company_name}' in {sub_city}. Ref: {inquiry_ref}. Contact: "
        "{phone_number}. SLA Window Active. Bring Fluke tester & backup "
        "switch pool."
    ).format(
        priority=priority,
        tier_name=tier_name,
        company_name=company_name,
        sub_city=sub_city,
        inquiry_ref=inquiry_ref,
        phone_number=phone_number,
    )
    return sms_text


if __name__ == "__main__":
    print("=== SAMPLE AUTOMATED CLIENT EMAIL ===")
    email = generate_client_confirmation_email(
        "Zemen Commercial Bank SC", "Bethlehem Tadesse", "RAMA-SLA-2026-0001", "Gold SLA", "< 2 Hours Priority", "Bole"
    )
    print("SUBJECT: {}\n".format(email["subject"]))
    print(email['body'])
    
    print("\n=== SAMPLE FIELD ENGINEER SMS DISPATCH ===")
    sms = generate_engineer_dispatch_sms("RAMA-SLA-2026-0001", "Zemen Commercial Bank SC", "Bole", "Gold SLA", "+251 911 234567")
    print(sms)
