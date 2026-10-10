from member_dashboard.sec_events import event_summary


def test_segment_change_reports_actual_event_not_form_definition():
    html='''<html><ix:hidden>hidden taxonomy fields</ix:hidden><p>FORM 8-K</p>
    <p>Item 7.01. Regulation FD Disclosure</p>
    <p>On September 2, 2026, Microsoft Corporation (the “Company”) posted presentation materials titled
    “FY27 Segments and Investor Metrics” announcing a change in reportable segments and investor metrics.
    Beginning in fiscal year 2027, the Company will report two segments: Agents and Infra and Devices and Consumer.</p>
    <p>A copy is furnished as Exhibit 99.1.</p><p>Item 9.01. Financial Statements and Exhibits</p></html>'''
    title,summary=event_summary(html)
    assert title=='Reporting segment changes'
    assert 'Agents and Infra' in summary and 'Devices and Consumer' in summary
    assert 'fiscal year 2027' in summary and 'hidden taxonomy' not in summary
    assert 'Filed for news such as' not in summary


def test_multiple_event_items_preserved_and_exhibits_excluded():
    title,summary=event_summary('<p>Item 2.02 Results of Operations and Financial Condition</p><p>The company announced revenue of $5 billion.</p><p>Item 5.02 Departure of Directors or Certain Officers</p><p>The CEO resigned effective Monday.</p><p>Item 9.01 Financial Statements and Exhibits</p><p>Exhibit 99.</p>')
    assert 'revenue of $5 billion' in summary and 'CEO resigned' in summary
    assert 'Exhibit 99' not in summary


def test_unreadable_document_never_returns_generic_event():
    assert event_summary('<html>Request rate threshold exceeded</html>') is None


def test_inline_heading_keeps_event_and_item_cross_reference():
    title,summary=event_summary('<p><b>Item 8.01 Other Events</b> On October 9, 2026, the company announced an acquisition valued at one billion dollars, with exhibits under Item 9.01 supporting the deal.</p>')
    assert 'acquisition valued at one billion dollars' in summary
    assert 'supporting the deal' in summary


def test_full_official_heading_is_not_mistaken_for_disclosure():
    title,summary=event_summary('<p>Item 5.02 Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers</p><p>The CEO resigned effective Monday.</p>')
    assert summary=='The CEO resigned effective Monday.'
