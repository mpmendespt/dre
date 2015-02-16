# -*- coding: utf-8 -*-

from django.contrib import sitemaps
from django.core.urlresolvers import reverse

class StaticViewSitemap(sitemaps.Sitemap):
    priority = 0.5
    changefreq = 'weekly'

    def items(self):
        return ['about', 'help', 'top']

    def location(self, item):
        return reverse(item)


