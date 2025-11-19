# tests/test_basic.py
import unittest
from flask import url_for
from app import create_app, db
from app.models import UserData, License

class BasicTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_app_exists(self):
        self.assertFalse(self.app is None)

    def test_home_page(self):
        response = self.client.get(url_for('index'))
        self.assertEqual(response.status_code, 200)

    def test_license_creation(self):
        license = License(key='TEST-1234')
        db.session.add(license)
        db.session.commit()
        self.assertIsNotNone(license.id)

    def test_invalid_license_login(self):
        response = self.client.post('/user-login', data={
            'license_key': 'INVALID-KEY'
        })
        self.assertIn('error', response.get_json())

if __name__ == '__main__':
    unittest.main()