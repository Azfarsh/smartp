from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"

    def items(self):
        # Keep this list to named, publicly crawlable pages.
        return [
            "home",
            "contact",
            "terms",
            "privacy",
        ]

    def location(self, item):
        return reverse(item)
