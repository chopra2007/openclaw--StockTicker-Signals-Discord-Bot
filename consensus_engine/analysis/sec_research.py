"""SEC collection policy without configuration, bot delivery or implicit clients."""
from .research_contracts import SecResearch, SecDetail


async def collect_sec(ticker, fetch_filings, fetch_form4) -> SecResearch:
    filings = await fetch_filings(ticker, 72)
    details = []
    if filings.status not in ('ok', 'partial'):
        return SecResearch(filings, (), 'partial')
    partial, count = filings.status == 'partial', 0
    for filing in filings.data:
        if filing.form != '4': continue
        outcome = None
        if count < 8:
            outcome = await fetch_form4(filing.cik, filing.accession_number, filing.primary_document)
            count += 1
        details.append(SecDetail(filing.accession_number, outcome))
        partial |= outcome is None or outcome.status != 'ok'
    return SecResearch(filings, tuple(details), 'partial' if partial else 'complete')
