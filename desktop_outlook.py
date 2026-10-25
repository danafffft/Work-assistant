"""Classic Outlook adapter. COM objects never cross request threads."""
from contextlib import contextmanager
from datetime import datetime, timezone


@contextmanager
def outlook():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        yield win32com.client.Dispatch('Outlook.Application').GetNamespace('MAPI')
    finally:
        pythoncom.CoUninitialize()


def connect():
    with outlook() as ns:
        inbox = ns.GetDefaultFolder(6)
        return str(inbox.StoreID)


def utc(value):
    return value.astimezone(timezone.utc)


def has_file_attachments(item):
    """Exclude hidden attachments and inline signature images from reports."""
    html = str(getattr(item, 'HTMLBody', '') or '').casefold()
    attachments = item.Attachments
    for index in range(1, attachments.Count + 1):
        attachment = attachments.Item(index)
        hidden, content_id = False, ''
        try:
            hidden = bool(attachment.PropertyAccessor.GetProperty(
                'http://schemas.microsoft.com/mapi/proptag/0x7FFE000B'))
        except Exception:
            pass  # Optional MAPI property may be absent on ordinary files.
        try:
            content_id = str(attachment.PropertyAccessor.GetProperty(
                'http://schemas.microsoft.com/mapi/proptag/0x3712001F') or '').strip('<>').casefold()
        except Exception:
            pass
        if hidden or (content_id and 'cid:' + content_id in html):
            continue
        return True
    return False


def messages(store_id):
    with outlook() as ns:
        inbox = ns.GetStoreFromID(store_id).GetDefaultFolder(6)
        items = inbox.Items
        items.Sort('[ReceivedTime]', True)
        result = []
        for index in range(1, min(items.Count, 100) + 1):
            item = items.Item(index)
            if item.Class not in (43, 53):
                continue
            address = str(item.SenderEmailAddress or '')
            try:
                if item.SenderEmailType == 'EX':
                    user = item.Sender.GetExchangeUser()
                    if user: address = str(user.PrimarySmtpAddress)
            except Exception:
                pass
            result.append({
                'id': str(item.EntryID),
                'subject': str(item.Subject or ''),
                'from': {'emailAddress': {'name': str(item.SenderName or ''), 'address': address}},
                'bodyPreview': str(item.Body or '')[:4000],
                'receivedDateTime': utc(item.ReceivedTime).isoformat(),
                'hasAttachments': has_file_attachments(item),
                'importance': {0: 'low', 1: 'normal', 2: 'high'}.get(item.Importance, 'normal'),
                '@odata.type': '#microsoft.graph.eventMessageRequest' if item.Class == 53 else '#microsoft.graph.message',
            })
        return result, items.Count > 100


def categorize(store_id, message, category_names):
    import re
    with outlook() as ns:
        item = ns.GetItemFromID(message['id'], store_id)
        # Outlook uses the Windows regional list separator.
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Control Panel\International') as key:
            separator = winreg.QueryValueEx(key, 'sList')[0]
        current = [c.strip() for c in re.split(re.escape(separator), str(item.Categories or '')) if c.strip()]
        item.Categories = (separator + ' ').join([c for c in current if c not in category_names] + [message['category']])
        item.Importance = {'low': 0, 'normal': 1, 'high': 2}[message['priority']]
        item.Save()


def open_message(store_id, message_id):
    with outlook() as ns:
        ns.GetItemFromID(message_id, store_id).Display()


def accept_if_free(store_id, message_id):
    with outlook() as ns:
        invitation = ns.GetItemFromID(message_id, store_id)
        # Create the tentative calendar copy when Outlook has not processed the invitation yet.
        appointment = invitation.GetAssociatedAppointment(True)
        if appointment is None:
            return 'Події ще немає в календарі — ручний перегляд'
        if appointment.ResponseStatus in (1, 3):
            return 'Вже прийнято'
        if appointment.IsRecurring or appointment.AllDayEvent:
            return 'Повторювана або цілоденна зустріч — ручний перегляд'
        start, end = utc(appointment.StartUTC), utc(appointment.EndUTC)
        if start <= datetime.now(timezone.utc) or end <= start:
            return 'Минулий або некоректний час — ручний перегляд'
        calendar = ns.GetStoreFromID(store_id).GetDefaultFolder(9).Items
        calendar.Sort('[Start]')
        calendar.IncludeRecurrences = True
        # Jet date filters use Outlook's local time. Inspect UTC overlap below too.
        local_start = appointment.Start.strftime('%m/%d/%Y %I:%M %p')
        local_end = appointment.End.strftime('%m/%d/%Y %I:%M %p')
        overlaps = calendar.Restrict(f"[Start] < '{local_end}' AND [End] > '{local_start}'")
        own_id = str(appointment.EntryID)
        for other in overlaps:
            if own_id and str(other.EntryID) == own_id:
                continue
            if utc(other.StartUTC) < end and utc(other.EndUTC) > start and other.BusyStatus != 0:
                return 'Конфлікт у календарі — ручний перегляд'
        # olMeetingAccepted=3. This sends a real response to the organizer.
        response = appointment.Respond(3, True, False)
        response.Send()
        return 'Автоматично прийнято'


def calendar_events(store_id, days=7):
    from datetime import timedelta
    now = datetime.now().astimezone()
    finish = now + timedelta(days=days)
    with outlook() as ns:
        items = ns.GetStoreFromID(store_id).GetDefaultFolder(9).Items
        items.Sort('[Start]')
        items.IncludeRecurrences = True
        start_text, end_text = now.strftime('%m/%d/%Y %I:%M %p'), finish.strftime('%m/%d/%Y %I:%M %p')
        filtered = items.Restrict(f"[Start] < '{end_text}' AND [End] > '{start_text}'")
        events = []
        for item in filtered:
            events.append({'id': str(item.EntryID), 'title': str(item.Subject or 'Нарада'), 'start': utc(item.StartUTC).isoformat(), 'end': utc(item.EndUTC).isoformat(), 'busy': item.BusyStatus != 0})
            if len(events) >= 1000: raise ValueError('Too many calendar occurrences')
        return events
