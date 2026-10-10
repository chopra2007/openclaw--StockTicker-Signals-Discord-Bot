from email.utils import formatdate
from member_dashboard.news import parse, parse_bing


def test_news_keeps_month_old_company_events_but_excludes_options():
    now = 1791586800
    titles = ['Microsoft launches a decision AI model', 'Microsoft unusual options activity',
              'MSFT call options see heavy volume', 'MSFT put option trade',
              'Microsoft puts new AI tools in Windows']
    items = ''.join(f'<item><title>{title}</title><pubDate>{formatdate(now-20*86400, usegmt=True)}</pubDate>'
                    f'<link>https://example.com/{i}</link></item>' for i, title in enumerate(titles))
    assert [row.title for row in parse('<rss>'+items+'</rss>', now=now)] == [titles[0], titles[4]]


def test_bing_excludes_options_before_limiting_headlines():
    now = 1791586800
    items = ''.join(f'<item><title>{title}</title><pubDate>{formatdate(now-86400, usegmt=True)}</pubDate>'
                    f'<link>https://bing.com/?url=https%3A%2F%2Fexample.com%2F{i}</link></item>'
                    for i, title in enumerate(['MSFT options activity', 'Microsoft announces a new product']))
    assert [row.title for row in parse_bing('<rss>'+items+'</rss>', now=now, limit=1)] == ['Microsoft announces a new product']


def test_live_options_quote_pages_are_not_headlines():
    from member_dashboard.news import options_story
    assert options_story('MSFT Oct 2026 467.500 put (MSFT261009P00467500) stock price, news, quote and history')
    assert options_story('MSFT Oct 2026 550.000 call Stock Price, News, Quote & History')
    assert not options_story('Microsoft puts new AI tools in Windows')
