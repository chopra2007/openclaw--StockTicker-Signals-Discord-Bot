"""Specific proposed sales and person names from SEC documents."""
from datetime import datetime
import math
import re
from xml.etree import ElementTree as ET


def person_name(raw, *, last_first=False):
    name=' '.join(raw.split())
    if name.isupper(): name=name.title()
    if re.search(r'\b(?:LLC|LP|Inc|Corp|Corporation|Trust|Holdings|Partners|Foundation)\b',name,re.I): return name
    suffix_match=re.search(r'(?:,\s*|\s+)(Jr\.?|Sr\.?|II|III|IV)$',name,re.I)
    suffix=suffix_match.group(1) if suffix_match else None
    if suffix_match: name=name[:suffix_match.start()].rstrip(', ')
    if ',' in name:
        last,first=name.split(',',1)
        return f'{first.strip()} {last.strip()}'+(f' {suffix}' if suffix else '')
    words=name.split()
    if last_first and len(words)>1:
        # SEC owner records are surname first; preserve common surname particles.
        count=1
        while count<len(words)-1 and words[count-1].lower() in ('van','von','de','del','der','da','di','la'):
            count+=1
        words=words[count:]+words[:count]
    return ' '.join(words+([suffix] if suffix else []))


def notice_summary(document):
    if '<!DOCTYPE' in document.upper() or '<!ENTITY' in document.upper(): return None
    try: root=ET.fromstring(document)
    except ET.ParseError: return None
    local=lambda node:node.tag.rsplit('}',1)[-1]
    def value(node,tag):
        return next(((child.text or '').strip() for child in node.iter() if local(child)==tag),'')
    if local(root)!='edgarSubmission' or value(root,'submissionType') not in ('144','144/A'): return None
    name=person_name(value(root,'nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold'))
    if not name: return None
    sales=[]
    for row in root.iter():
        if local(row)!='securitiesInformation': continue
        try:
            units=float(value(row,'noOfUnitsSold').replace(',',''))
            if not math.isfinite(units) or units<=0 or not units.is_integer(): return None
            raw_value=value(row,'aggregateMarketValue').replace(',','')
            amount=float(raw_value) if raw_value else None
            if amount is not None and (not math.isfinite(amount) or amount<0): return None
            raw_date=value(row,'approxSaleDate')
            date=datetime.strptime(raw_date,'%m/%d/%Y') if raw_date else None
        except ValueError: return None
        worth=f' (~**${amount/1e6:,.1f}M**)' if amount is not None and amount>=1e6 else f' (~**${amount:,.0f}**)' if amount is not None else ''
        when=f' around **{date.strftime("%b")} {date.day}, {date.year}**' if date else ' (sale date not provided)'
        sales.append(f'**{units:,.0f} shares**{worth}{when}')
        if len(sales)>10: return None
    return f'{name} proposed selling '+ '; '.join(sales)+'.' if sales else None


def canonical_notice_name(summary,owner_names):
    """Resolve ambiguous Form 144 order using the same person's Form 4 identity."""
    name,separator,rest=summary.partition(' proposed selling ')
    key=lambda text:sorted(re.findall(r'[\w]+',text.casefold()))
    for owner in owner_names:
        if key(name)==key(owner):
            return person_name(owner,last_first=True)+separator+rest
    return summary
