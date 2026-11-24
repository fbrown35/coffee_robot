import time
from email.utils import formatdate

from coffee_robot.news import NewsService, parse_rss

RSS = f"""<?xml version="1.0"?><rss><channel>
<item><title>로봇이 커피를 탄다 - 테크뉴스</title><source>테크뉴스</source>
<pubDate>{formatdate(time.time() - 3600)}</pubDate><link>http://a</link></item>
<item><title>옛날 기사 - 신문</title><source>신문</source>
<pubDate>{formatdate(time.time() - 5 * 86400)}</pubDate><link>http://b</link></item>
</channel></rss>"""


class FakeHttp:
    def get(self, url, **kw):
        self.url = url

        class R:
            text = RSS

            def raise_for_status(self):
                pass
        return R()


def test_parse_strips_source():
    arts = parse_rss(RSS)
    assert arts[0].title == "로봇이 커피를 탄다" and arts[0].source == "테크뉴스"


def test_fetch_filters_old_and_unknown_category():
    http = FakeHttp()
    svc = NewsService({"categories": {"로봇": "로봇"}}, session=http)
    items = svc.fetch("로봇")
    assert [a.title for a in items] == ["로봇이 커피를 탄다"]
    assert "hl=ko" in http.url
    out = svc.briefing(["없는범주"])
    assert "error" in out["없는범주"]
