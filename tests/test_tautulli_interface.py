import unittest
from unittest.mock import patch

from modules.TautulliInterface import TautulliInterface


class ParseRecentlyAddedTests(unittest.TestCase):
    def test_handles_top_level_data_list(self) -> None:
        response = {'response': {'data': [{'id': 1}]}}

        entries, source = TautulliInterface._parse_recently_added(response)

        self.assertEqual(entries, [{'id': 1}])
        self.assertEqual(source, 'response.data')

    def test_handles_nested_recently_added_data(self) -> None:
        response = {
            'response': {
                'data': {
                    'recently_added': {
                        'data': [{'id': 2}],
                    },
                },
            },
        }

        entries, source = TautulliInterface._parse_recently_added(response)

        self.assertEqual(entries, [{'id': 2}])
        self.assertEqual(source, 'response.data.recently_added.data')

    def test_handles_top_level_records(self) -> None:
        response = {
            'response': {
                'data': {
                    'records': [{'id': 3}],
                },
            },
        }

        entries, source = TautulliInterface._parse_recently_added(response)

        self.assertEqual(entries, [{'id': 3}])
        self.assertEqual(source, 'response.data.records')

    def test_handles_recently_added_records(self) -> None:
        response = {
            'response': {
                'data': {
                    'recently_added': {
                        'records': [{'id': 4}],
                    },
                },
            },
        }

        entries, source = TautulliInterface._parse_recently_added(response)

        self.assertEqual(entries, [{'id': 4}])
        self.assertEqual(source, 'response.data.recently_added.records')

    def test_logs_warning_when_schema_unrecognized(self) -> None:
        response = {
            'response': {
                'data': {
                    'unexpected': {'id': 5},
                },
            },
        }

        with patch('modules.TautulliInterface.log') as mock_log:
            entries, source = TautulliInterface._parse_recently_added(response)

        self.assertEqual(entries, [])
        self.assertEqual(source, 'none')
        mock_log.warning.assert_called()


if __name__ == '__main__':
    unittest.main()
