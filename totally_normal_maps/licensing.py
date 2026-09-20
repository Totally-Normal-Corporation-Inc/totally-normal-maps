"""Separate publisher licence evidence from a maintainer's publication decision."""
from .layers import public_url, valid_date


def redistribution_approved(source):
    """An explicit government-source decision does not assert publisher permission."""
    if source.get('redistribution_status') == 'permitted':
        return True
    if source.get('redistribution_status') != 'unconfirmed':
        return False
    decision = source.get('publication_decision')
    evidence = source.get('licence_evidence')
    disclaimer = source.get('publication_disclaimer')
    return bool(
        isinstance(decision, dict)
        and decision.get('status') == 'approved_by_maintainer'
        and decision.get('source_type') == 'government'
        and valid_date(decision.get('reviewed_on'))
        and isinstance(decision.get('basis'), str) and bool(decision['basis'].strip())
        and isinstance(decision.get('contact'), str) and '@' in decision['contact']
        and isinstance(disclaimer, str) and decision['contact'] in disclaimer
        and isinstance(source.get('attribution_statement'), str)
        and bool(source['attribution_statement'].strip())
        and isinstance(source.get('licence_review'), str) and bool(source['licence_review'].strip())
        and isinstance(evidence, list) and bool(evidence)
        and all(isinstance(item, dict) and public_url(item.get('url'))
                and isinstance(item.get('finding'), str) and bool(item['finding'].strip())
                for item in evidence)
    )
