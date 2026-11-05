def query_string_without_page(query):
    query = query.copy()
    query.pop('page', None)
    for key in list(query):
        values = [value for value in query.getlist(key) if value]
        if values:
            query.setlist(key, values)
        else:
            query.pop(key, None)
    return query.urlencode()
