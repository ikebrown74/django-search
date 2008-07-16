from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from djangosearch.backends import base
from djangosearch.indexer import get_indexer, get_indexed_models
from djangosearch.models import Document
from djangosearch.query import RELEVANCE, QueryConverter, convert_new
from djangosearch.results import SearchResults

qn = connection.ops.quote_name

class SearchEngine(base.DocumentSearchEngine):
    """
    A MySQL FULLTEXT search engine.
    """
    
    def __init__(self):
        if settings.DATABASE_ENGINE != "mysql":
            raise ImproperlyConfigured('The mysql search engine requires the mysql database engine.')
    
    def search(self, query, models=None, order_by=RELEVANCE, limit=None, offset=None):
        (conv_query, fields) = convert_new(query, MysqlQueryConverter)
        if not conv_query:
            return SearchResults(q, [], 0, lambda x: x)
        if not models:
            models = get_indexed_models()
        doc_table = qn(Document._meta.db_table)
        content_types = []
        params = []
        for model in models:
            content_types.append("%s.%s = %%s" 
                                  % (doc_table, qn("content_type_id")))
            params.append(ContentType.objects.get_for_model(model).pk)
        match = "MATCH(%s.%s) AGAINST(%%s IN BOOLEAN MODE)" \
                 % (doc_table, qn("text"))
        sql_order_by = "-relevance" # TODO: fields
        results = Document.objects.extra(
                    select={'relevance': match},
                    select_params=[conv_query],
                    where=[match, " OR ".join(content_types)],
                    params=[conv_query] + params).order_by(sql_order_by)
        if limit is not None:
            if offset is not None:
                results = results[offset:offset+limit]
            else:
                results = results[:limit]
        return SearchResults(query, results, results.count(), 
                    self._result_callback)
                    

class MysqlQueryConverter(QueryConverter):
    QUOTES          = '""'
    GROUPERS        = "()"
    AND             = "+"
    OR              = " "
    NOT             = "-"
    SEPARATOR       = ' '
    FIELDSEP        = ':'
    
    def __init__(self):
        QueryConverter.__init__(self)
        self.in_not = False
        self.in_or = False
        
    def handle_term(self, term):
        if not self.in_quotes and not self.in_not and not self.in_or:
            self.converted.write(self.AND)
        self.converted.write(term)
        self.write_sep()
    
    def start_not(self):
        self.converted.write(self.NOT)
        self.in_not = True

    def end_not(self):
        self.in_not = False

    def start_or(self):
        self.sepstack.append(self.OR)
        self.in_or = True

    def end_or(self):
        self.in_or = False

    def start_group(self):
        if not self.in_not:
            self.converted.write(self.AND)
        self.converted.write(self.GROUPERS[0])
        