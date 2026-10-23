from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch
import desktop_outlook as desktop


class CalendarTests(TestCase):
    def scenario(self, conflict=False, recurrence=False, missing=False):
        start = datetime(2099, 1, 1, 10, tzinfo=timezone.utc)
        end = datetime(2099, 1, 1, 11, tzinfo=timezone.utc)
        response = Mock()
        appointment = NS(ResponseStatus=5, IsRecurring=recurrence, AllDayEvent=False,
                         StartUTC=start, EndUTC=end, Start=start, End=end,
                         EntryID='own', Respond=Mock(return_value=response))
        own = NS(EntryID='own', StartUTC=start, EndUTC=end, BusyStatus=1)
        other = NS(EntryID='other', StartUTC=start, EndUTC=end, BusyStatus=2 if conflict else 0)
        items = Mock()
        items.Restrict.return_value = [own, other]
        ns = Mock()
        ns.GetItemFromID.return_value.GetAssociatedAppointment.return_value = None if missing else appointment
        ns.GetStoreFromID.return_value.GetDefaultFolder.return_value.Items = items
        @contextmanager
        def fake(): yield ns
        with patch.object(desktop, 'outlook', fake):
            result = desktop.accept_if_free('store', 'message')
        return result, appointment, response

    def test_free_and_own_tentative_is_accepted(self):
        result, appointment, response = self.scenario()
        self.assertEqual(result, 'Автоматично прийнято')
        appointment.Respond.assert_called_once_with(3, True, False)
        response.Send.assert_called_once()

    def test_conflict_never_sends(self):
        result, appointment, response = self.scenario(conflict=True)
        self.assertIn('Конфлікт', result)
        appointment.Respond.assert_not_called()
        response.Send.assert_not_called()

    def test_recurrence_never_sends(self):
        result, appointment, response = self.scenario(recurrence=True)
        self.assertIn('ручний', result)
        appointment.Respond.assert_not_called()

    def test_missing_calendar_copy_never_sends(self):
        result, appointment, response = self.scenario(missing=True)
        self.assertIn('ручний', result)
        response.Send.assert_not_called()


class AttachmentTests(TestCase):
    def item(self, attachments, html=''):
        collection = Mock(Count=len(attachments))
        collection.Item.side_effect = lambda index: attachments[index - 1]
        return NS(Attachments=collection, HTMLBody=html)

    def attachment(self, hidden=False, cid=''):
        accessor = Mock()
        accessor.GetProperty.side_effect = [hidden, cid]
        return NS(PropertyAccessor=accessor)

    def test_file_is_report(self):
        self.assertTrue(desktop.has_file_attachments(self.item([self.attachment()])))

    def test_signature_is_not_report(self):
        self.assertFalse(desktop.has_file_attachments(self.item([self.attachment(cid='logo')], '<img src="cid:logo">')))

    def test_hidden_is_not_report(self):
        self.assertFalse(desktop.has_file_attachments(self.item([self.attachment(hidden=True)])))

    def test_signature_and_file_is_report(self):
        self.assertTrue(desktop.has_file_attachments(self.item([self.attachment(cid='logo'), self.attachment()], '<img src="cid:logo">')))

    def test_no_files(self):
        self.assertFalse(desktop.has_file_attachments(self.item([])))
