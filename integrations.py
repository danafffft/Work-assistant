"""Read-only Jira and Teams inputs. Credentials are never returned to the UI."""
import base64
import os
import urllib.parse


def jira_tasks(request, settings=None):
    settings = settings or {}
    base = settings.get('url') or os.getenv('JIRA_URL', '').rstrip('/')
    token = settings.get('token') or os.getenv('JIRA_API_TOKEN', '')
    if not base or not token:
        return [], 'Jira не підключено. Вкажіть адресу та API-токен у налаштуваннях Jira.'
    url = urllib.parse.urlsplit(base)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('JIRA_URL must be an HTTPS base URL')
    cloud = url.hostname.endswith('.atlassian.net')
    email = settings.get('email') or os.getenv('JIRA_EMAIL', '')
    if cloud and not email:
        return [], 'Для Jira Cloud також потрібен JIRA_EMAIL.'
    auth = 'Basic ' + base64.b64encode((email + ':' + token).encode()).decode() if cloud else 'Bearer ' + token
    jql = 'assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC, duedate ASC'
    fields = 'summary,priority,duedate,timeestimate,status'
    tasks, cursor = [], None
    for page in range(10):
        params = {'jql': jql, 'fields': fields, 'maxResults': 100}
        if cloud:
            if cursor: params['nextPageToken'] = cursor
            endpoint = '/rest/api/3/search/jql'
        else:
            params['startAt'] = page * 100
            endpoint = '/rest/api/2/search'
        data = request(base + endpoint + '?' + urllib.parse.urlencode(params), headers={'Authorization': auth}, no_redirect=True)
        for issue in data.get('issues', []):
            f = issue['fields']
            tasks.append({'id': 'jira:' + issue['key'], 'title': issue['key'] + ' · ' + f['summary'], 'source': 'Jira', 'url': base + '/browse/' + urllib.parse.quote(issue['key'], safe=''), 'due': f.get('duedate'), 'minutes': max(15, (f.get('timeestimate') or 3600)//60), 'rank': int((f.get('priority') or {}).get('id', 3)) if str((f.get('priority') or {}).get('id', 3)).isdigit() else 3})
        cursor = data.get('nextPageToken')
        if cloud and (data.get('isLast') or not cursor): return tasks, 'Jira оновлено.'
        if not cloud and (page+1)*100 >= data.get('total', 0): return tasks, 'Jira оновлено.'
    return tasks, 'Jira: завантажено перші 1000 задач; список неповний.'


def mentioned_tasks(messages, user_id, chat_id):
    from html import unescape
    import re
    result = []
    for m in messages:
        if m.get('deletedDateTime') or m.get('messageType', 'message') != 'message': continue
        if not any(mention.get('mentioned', {}).get('user', {}).get('id') == user_id for mention in m.get('mentions', [])): continue
        content = unescape(re.sub('<[^>]+>', ' ', m.get('body', {}).get('content', '')))
        content = ' '.join(content.split())
        if not content: continue
        result.append({'id': 'teams:' + chat_id + ':' + m['id'], 'title': content[:500], 'source': 'Teams · згадка', 'url': m.get('webUrl', ''), 'minutes': 30, 'rank': 3, 'due': None})
    return result
