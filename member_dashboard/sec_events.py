"""Extract the actual 8-K disclosure without an AI call or form-definition fallback."""
from html.parser import HTMLParser
import re


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.hidden=0

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','ix:hidden','ix:header'): self.hidden+=1
        if not self.hidden and tag in ('p','div','tr','h1','h2','h3','br'): self.parts.append('\x00')

    def handle_endtag(self,tag):
        if tag in ('script','style','ix:hidden','ix:header'): self.hidden=max(0,self.hidden-1)
        if not self.hidden and tag in ('p','div','tr','h1','h2','h3'): self.parts.append('\x00')

    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)


_HEADINGS={'1.01':'Entry into a Material Definitive Agreement','1.02':'Termination of a Material Definitive Agreement',
           '1.03':'Bankruptcy or Receivership','2.01':'Completion of Acquisition or Disposition of Assets',
           '2.02':'Results of Operations and Financial Condition','2.03':'Creation of a Direct Financial Obligation',
           '2.05':'Costs Associated with Exit or Disposal Activities','2.06':'Material Impairments',
           '3.01':'Notice of Delisting','3.02':'Unregistered Sales of Equity Securities',
           '5.02':'Departure of Directors or Certain Officers','5.07':'Submission of Matters to a Vote of Security Holders',
           '7.01':'Regulation FD Disclosure','8.01':'Other Events','9.01':'Financial Statements and Exhibits'}
_TITLES={'1.01':'Material agreement','1.02':'Agreement terminated','1.03':'Bankruptcy update',
         '2.01':'Acquisition or asset sale','2.02':'Earnings update','2.03':'Financing update',
         '2.05':'Restructuring update','2.06':'Asset impairment','3.01':'Listing update',
         '3.02':'Share issuance','5.02':'Leadership update','5.07':'Shareholder vote',
         '7.01':'Company disclosure','8.01':'Company update'}


def _brief(paragraph):
    segments=re.search(r'(?:Beginning in|Starting in) fiscal year (\d{4}).*?(?:reportable )?segments:\s*\(1\)\s*(.+?)\s+and\s*\(2\)\s*(.+?)(?:\.(?:\s|$)|$)',paragraph,re.I)
    if segments:
        year,first,second=segments.groups()
        return f'From **FY{year}**, financial results will be reported in two segments: **{first}** and **{second}**.'
    # Keep the announcement sentence; omit exhibit and website boilerplate.
    sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])',paragraph)
    useful=[s for s in sentences if not re.search(r'^(?:A copy|The foregoing|This information|Pursuant to)',s,re.I)]
    brief=useful[0] if useful else paragraph
    return brief if len(brief)<=360 else brief[:357].rsplit(' ',1)[0]+'…'


def event_summary(document):
    parser=_Text();parser.feed(document)
    text='\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).split('\x00') if line.strip())
    headings=list(re.finditer(r'^Item\s+(\d+\.\d{2})\b[.\s]*',text,re.I|re.M))
    excerpts=[];titles=[]
    for i,heading in enumerate(headings):
        code=heading.group(1)
        if code=='9.01': continue
        section=text[heading.end():headings[i+1].start() if i+1<len(headings) else len(text)]
        section=re.split(r'\bSIGNATURES?\b',section,flags=re.I)[0].strip()
        lines=section.splitlines()
        prefix=_HEADINGS.get(code,'')
        if lines and prefix and lines[0].lower().startswith(prefix.lower()):
            remainder=lines[0][len(prefix):].lstrip(' .;:—–-')
            tails={'5.02':'Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers',
                   '2.03':'or an Obligation under an Off-Balance Sheet Arrangement of a Registrant',
                   '3.01':'or Failure to Satisfy a Continued Listing Rule or Standard; Transfer of Listing'}
            tail=tails.get(code,'')
            if tail and remainder.lower().startswith(tail.lower()):
                remainder=remainder[len(tail):].lstrip(' .;:—–-')
            lines=([remainder] if remainder else [])+lines[1:]
        if not lines: continue
        # The first substantive paragraph, not the cover page or exhibit boilerplate.
        paragraph=lines[0].strip()
        if len(paragraph)<25: continue
        excerpts.append(_brief(paragraph))
        titles.append('Reporting segment changes' if re.search(r'reportable segments|reporting structure',paragraph,re.I) else _TITLES.get(code,'Company disclosure'))
        if len(excerpts)==3: break
    return (' / '.join(dict.fromkeys(titles))[:256], ' '.join(excerpts)) if excerpts else None
