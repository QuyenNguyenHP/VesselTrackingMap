import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from fastapi import HTTPException
from backend.main import lookup_vessel
from backend.lookup import lookup_openwaters


class LookupTests(unittest.TestCase):
    def feature(self, coordinates=None):
        return io.BytesIO(json.dumps({'type': 'Feature', 'properties': {'mmsi': 257123000, 'imo': 9796896, 'name': 'GRANIT'}, 'geometry': {'coordinates': coordinates or [24, 72]}}).encode())

    def test_invalid_identifiers(self):
        for value in ('abc', '123', '9796896', '12345678', '1234567890', '１２３４５６７'):
            with self.assertRaises(HTTPException) as error:
                lookup_vessel(value)
            self.assertEqual(error.exception.status_code, 400)

    @patch('backend.main.list_vessels', return_value=[{'mmsi': '257123000', 'imo': 9796896}])
    @patch('backend.main.lookup_openwaters')
    def test_local_mmsi_does_not_need_provider(self, remote, local):
        self.assertEqual(lookup_vessel('257123000')['mmsi'], '257123000')
        remote.assert_not_called()

    @patch('backend.main.list_vessels', return_value=[])
    @patch('backend.lookup.urlopen')
    def test_remote_mmsi_without_authentication(self, request, local):
        for identifier in ('257123000',):
            request.return_value = self.feature()
            vessel = lookup_vessel(identifier)
            self.assertEqual(vessel['mmsi'], '257123000')
            self.assertTrue(vessel['position_available'])
            self.assertEqual(vessel['latitude'], 72)
            self.assertEqual(vessel['lookup_source'], 'remote')
            self.assertFalse(request.call_args.args[0].has_header('Authorization'))

    @patch('backend.lookup.urlopen')
    def test_invalid_coordinates(self, request):
        request.return_value = self.feature([181, 91])
        self.assertIsNone(lookup_openwaters('257123000')['position'])

    @patch('backend.lookup.urlopen')
    def test_provider_failures(self, request):
        for code, expected in ((404, 404), (403, 503), (429, 429), (500, 502)):
            request.side_effect = HTTPError('https://example.test', code, '', {}, None)
            with self.assertRaises(HTTPException) as error:
                lookup_openwaters('257123000')
            self.assertEqual(error.exception.status_code, expected)
        request.side_effect = URLError('offline')
        with self.assertRaises(HTTPException) as error:
            lookup_openwaters('257123000')
        self.assertEqual(error.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
