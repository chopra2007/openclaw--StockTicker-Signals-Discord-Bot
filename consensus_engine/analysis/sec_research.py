"""SEC collection policy without configuration, bot delivery or implicit clients."""
from .research_contracts import SecResearch, SecDetail


async def collect_sec(ticker, fetch_filings, fetch_form4) -> SecResearch:
    filings = await fetch_filings(ticker, 72)
    details = []
    if filings.status not in ('ok', 'partial'):
        return SecResearch(filings, (), 'partial')
    partial = filings.status == 'partial'
    for filing in filings.data:
        if filing.form != '4': continue
        # The caller bounds the displayed filing list. Fetch each of its Form 4s;
        # an independent eight-detail cap left visible filings unrequested.
        outcome = await fetch_form4(filing.cik, filing.accession_number, filing.primary_document)
        details.append(SecDetail(filing.accession_number, outcome))
        partial |= outcome is None or outcome.status != 'ok'
    return SecResearch(filings, tuple(details), 'partial' if partial else 'complete')
