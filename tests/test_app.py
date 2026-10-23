import unittest
from unittest.mock import patch
import app

class Rules(unittest.TestCase):
    def message(self, sender='person@example.com', subject='Привіт', **extra):
        return {'from': {'emailAddress': {'address': sender, 'name': 'Олена Коваль'}}, 'subject': subject, **extra}
    def test_people(self): self.assertEqual(app.classify(self.message())['category'], 'Від людей')
    def test_manageengine_is_automatic(self):
        m = self.message('dell@universalna.onmicrosoft.com', 'Alert from ManageEngine OpUtils Rogue Detection tool')
        m['from']['emailAddress']['name'] = 'dell'
        self.assertEqual(app.classify(m)['category'], 'Автоматичні повідомлення')

    def test_automation_overrides_person_name(self):
        self.assertEqual(app.classify(self.message(subject='Alert from ManageEngine OpUtils Rogue Detection tool'))['category'], 'Автоматичні повідомлення')

    def test_unclear_names_are_not_people(self):
        for name in ('', 'dell', 'Olena', 'IT Support', 'Security Team', 'Олена123 Коваль', 'olena@example.com'):
            with self.subTest(name=name):
                m = self.message()
                m['from']['emailAddress']['name'] = name
                self.assertEqual(app.classify(m)['category'], 'Автоматичні повідомлення')

    def test_person_names(self):
        for name in ('Олена Коваль', 'John Smith', 'Анна-Марія Петренко', "Mary O’Connor"):
            with self.subTest(name=name):
                m = self.message()
                m['from']['emailAddress']['name'] = name
                self.assertEqual(app.classify(m)['category'], 'Від людей')

    def test_reports_override_sender_and_subject_categories(self):
        for sender, subject in [('person@example.com', 'Документ'), ('jira@example.com', 'Jira export'), ('dell@example.com', 'Alert from ManageEngine')]:
            with self.subTest(sender=sender):
                self.assertEqual(app.classify(self.message(sender, subject, hasAttachments=True))['category'], 'Звіти')

    def test_report_subject_without_file_is_not_report(self):
        self.assertNotEqual(app.classify(self.message(subject='Щотижневий звіт', hasAttachments=False))['category'], 'Звіти')

    def test_categories(self):
        for address, subject, category in [('jira@example.com','Оновлено','Jira'),('noreply@example.com','Confluence update','Confluence'),('noreply@example.com','Навчання Python','Навчання'),('noreply@example.com','Звіт','Автоматичні повідомлення')]:
            with self.subTest(category=category): self.assertEqual(app.classify(self.message(address,subject))['category'],category)
    def test_priority(self):
        self.assertEqual(app.classify(self.message(subject='Терміново: допомога'))['priority'],'high')
        self.assertEqual(app.classify(self.message('noreply@example.com'))['priority'],'low')
        self.assertEqual(app.classify(self.message(importance='high'))['priority'],'high')
    def test_fail_closed(self):
        for schedule in [{}, {'value':[]}, {'value':[{'error':{}}]}, {'value':[{'scheduleItems':[{'status':'busy'}]}]}]: self.assertFalse(app.can_accept({}, schedule))
    def test_free(self): self.assertTrue(app.can_accept({}, {'value':[{'scheduleItems':[]}]}))
    def test_recurrence(self): self.assertFalse(app.can_accept({'recurrence':{'pattern':{}}}, {'value':[{'scheduleItems':[]}]}))
    @patch('app.graph')
    def test_calendar_failure_never_accepts(self, graph):
        graph.side_effect=ValueError('unavailable')
        self.assertIn('ручний', app.auto_accept({}, {'id':'1'}))
        self.assertEqual(graph.call_count,1)
    @patch('app.graph')
    def test_free_meeting_accepted(self, graph):
        graph.side_effect=[{'start':{'dateTime':'2099-01-01T10:00:00','timeZone':'UTC'},'end':{'dateTime':'2099-01-01T11:00:00','timeZone':'UTC'}},{'mail':'me@example.com'},{'value':[{'scheduleItems':[]}]},{}]
        self.assertEqual(app.auto_accept({}, {'id':'1'}),'Автоматично прийнято')
        self.assertEqual(graph.call_args.args[1],'/me/messages/1/accept')
    @patch('app.graph')
    def test_busy_meeting_not_accepted(self, graph):
        graph.side_effect=[{'start':{'dateTime':'2099-01-01T10:00:00','timeZone':'UTC'},'end':{'dateTime':'2099-01-01T11:00:00','timeZone':'UTC'}},{'mail':'me@example.com'},{'value':[{'scheduleItems':[{'status':'busy'}]}]}]
        self.assertIn('Конфлікт',app.auto_accept({}, {'id':'1'}))
        self.assertEqual(graph.call_count,3)

if __name__=='__main__': unittest.main()
