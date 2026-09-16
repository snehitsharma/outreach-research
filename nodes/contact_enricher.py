from state import State
from tools import apollo_tool


def contact_enrichment_node(state: State) -> dict:
    """Enrich discovered contacts through Apollo for sales outreach jobs."""
    contacts = state.verified_contacts or []

    if not state.is_sales_outreach or not contacts:
        return {"verified_contacts": contacts}

    enriched_contacts = []
    seen_names = set()

    for contact in contacts:
        if not contact.name:
            continue

        normalized_name = contact.name.strip().lower()
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)

        if not contact.email or contact.email == "N/A":
            apollo_result = apollo_tool.run(name=contact.name, company=contact.company)
            contact.email = apollo_result.get("email")
            if not contact.role:
                contact.role = apollo_result.get("title")

        enriched_contacts.append(contact)

    return {"verified_contacts": enriched_contacts}
