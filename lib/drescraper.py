# -*- coding: utf-8 -*-

'''This module will scan and scrap the dre.pt site'''

##
## Imports
##

from datetime import datetime, timedelta
import time
import random
import re
import sys
import os.path

# Append the current project path
sys.path.append(os.path.abspath('../lib/'))
sys.path.append(os.path.abspath('../dre_django/'))

# Django general
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Max

from dreapp.models import Document 
from drelog import logger

# Local Imports
from mix_utils import fetch_url
from dreerror import DREError
import bs4 



##
## Scrap the entire site
##

TOLERANCE = timedelta(0, 120)

class DRESession( object ):
    '''This class manages the DRE session:
        * Manages cookies;
        * Accounts for cookie expiration;
        * Gets and manage the url unique marker;
    '''
    def __init__(self):
        self.cookies = None
        self.unique_marker = None
        self.cookie_timeout = datetime(1970,01,01)

    def cookie_is_stale(self):
        return datetime.now() > ( self.cookie_timeout + TOLERANCE )

    def renew_cookie(self):
        url, payload, cj  =  fetch_url('http://www.dre.pt/sug/digesto/rgratis.asp?reg=PCMLex')
        self.cookies = cj
        self.cookie_timeout = datetime.fromtimestamp(list(cj)[0].expires)

    def renew_marker(self):
        logger.warn('Renewing cookies and marker.')
        assert self.cookies != None, 'No cookie jar...'

        url, payload, cj  =  fetch_url('http://digestoconvidados.dre.pt/digesto/Main.aspx?Database=LEX', cj=self.cookies )
        self.unique_marker = re.search(r'\(S\((.+)\)\)', url).groups()[0]
        self.cookies = cj

    def download_page(self, url ):
        if self.cookie_is_stale():
            self.renew_cookie()
            self.renew_marker()

        url, html, cj  =  fetch_url(url % { 
            'unique_marker': self.unique_marker, })

        return html 


class DREReadDocs( object ):
    '''Reads a document and stores it in the database.
    '''
    def __init__(self, dre_session):
        self.dre_session = dre_session

    def fetch_document(self, claint):    
        base_url = 'http://digestoconvidados.dre.pt/digesto/(S(%(unique_marker)s))/Paginas'
        url =  base_url + '/DiplomaDetalhado.aspx?claint=%(claint)d' % { 'claint': claint } 
        url_pdf =  base_url + '/DiplomaTexto.aspx' 

        self.html = self.dre_session.download_page( url )
        self.html_pdf = self.dre_session.download_page( url_pdf )

        f = open('%d-test.html' % claint, 'w')
        f.write(self.html)
        f.close()
        f = open('%d-pdf.html' % claint, 'w')
        f.write(self.html_pdf)
        f.close()

    def soupify(self):
        self.soup = bs4.BeautifulSoup(self.html) 
        self.soup_pdf = bs4.BeautifulSoup(self.html_pdf) 
        
    def parse(self):
        page_result = {}

        page_result['claint'] = self.claint

        page_result['doc_type'] = self.soup.find('td', 
                { 'headers': 'tipoDescricaoIDHeader' }
                ).renderContents() 

        page_result['number'] = self.soup.find('td', 
                { 'headers': 'numeroIDHeader' }
                ).renderContents() 

        page_result['emiting_body'] = self.soup.find('td', 
                { 'headers': 'entidadesEmitentesIDHeader' }
                ).renderContents() 

        try:
            page_result['source'] = self.soup.find('td', 
                    { 'headers': 'fonteIDHeader' }
                    ).renderContents() 
        except AttributeError:
            page_result['source'] = ''
        
        try:
            page_result['dre_key'] = self.soup.find('td', 
                    { 'headers': 'ChaveDreIDHeader' }
                    ).renderContents() 
        except AttributeError:
            page_result['dre_key'] = ''

        try:
            page_result['date'] = datetime.strptime(self.soup.find('td', 
                    { 'headers': 'dataAssinaturaIDHeader' }
                    ).renderContents(), '%d.%m.%Y') 
        except AttributeError:
            # Tries to get the date from the legend header
            legend = self.soup.find('legend').renderContents()
            search = re.search(r'(\d{2}\.\d{2}\.\d{4})', legend)
            if search:
                date_str = search.groups()[0]
                page_result['date'] = datetime.strptime( date_str, '%d.%m.%Y')
                logger.warn('Date extracted from legend: %s' % date_str)
            else:
                raise

        page_result['notes'] = self.soup.find('fieldset', 
                { 'id': 'FieldsetResumo' }
                ).find('div').renderContents().strip()

        try:
            page_result['plain_text'] = self.soup_pdf.find('span', 
                    { 'id': 'textoIntegral_textoIntegralResidente',
                      'class': 'TextoIntegralMargin' }
                    ).find('a')['href']  
        except TypeError:
            page_result['plain_text'] = ''
                    
        try:
            page_result['dre_pdf'] = self.soup_pdf.find('span', 
                    { 'id': 'textoIntegral_imagemDoDre',
                      'class': 'TextoIntegralMargin' }
                    ).find('a')['href']  
        except TypeError:
            page_result['dre_pdf'] = ''

        self.page_result = page_result

        logger.debug('''
    claint: %(claint)s
    doc_type: %(doc_type)s
    number: %(number)s
    emiting_body: %(emiting_body)s
    source: %(source)s
    dre_key: %(dre_key)s
    date: %(date)s
    notes: %(notes)s
    plain_text: %(plain_text)s
    dre_pdf: %(dre_pdf)s''' % page_result)


    def save(self):
        document = Document()
        page_result = self.page_result 

        document.claint = page_result['claint']
        document.doc_type = page_result['doc_type']
        document.number = page_result['number']
        document.emiting_body = page_result['emiting_body']
        document.source = page_result['source']
        document.dre_key = page_result['dre_key']
        document.date = page_result['date']
        document.notes = page_result['notes']
        document.plain_text = page_result['plain_text']
        document.dre_pdf = page_result['dre_pdf']

        document.save()

    def read_document( self, claint ):
        self.claint = claint 

        self.fetch_document(claint)
        self.soupify()
        self.parse()

        self.save()

class DREScrap( object ):
    '''Read the documents from the site. Stores the last publiched document.
    '''

    def __init__(self):
        self.reader = DREReadDocs( DRESession() )

    def last_read_doc(self):
        '''Gets the claint of the last read document'''
        max_claint = Document.objects.aggregate(Max('claint'))['claint__max']
        return max_claint if max_claint else 0
    
    def run(self):
        last_claint = self.last_read_doc() + 1
        while True:
            logger.warn('*** Getting %d' % last_claint)
            try:
                self.reader.read_document( last_claint )
            except DREError, msg:
                # Error reading the document. Will sleep 20 seconds and then
                # we try again.
                time.sleep( 20.0 * random.random() + 5 )
                continue
            except Exception, msg:
                raise 
                break
                
            t = 20.0 * random.random() + 5   
            logger.debug('Incrementing the counter. Sleeping %ds' % t)
            last_claint += 1
            time.sleep( t )


