import json
import tempfile
import unittest
from pathlib import Path

from app import FIELDS, create_app


class DashboardTest(unittest.TestCase):
    def test_six_month_overview_alerts_and_return_link(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            submissions = []
            for month, satisfaction, workload in [(1, 5, 5), (2, 4, 2), (4, 5, 4)]:
                scores = dict.fromkeys(FIELDS["intern"]["scores"].values(), 4)
                scores.update(satisfaction=satisfaction, workload=workload)
                submissions.append(dict(source="synthetic_demo", form_id="intern",
                                        submission_id=f"demo-{month}", intern_id="DEMO-1",
                                        department="IT", period=month, role="intern", mentor_id=None,
                                        submitted_at=None, scores=scores, comments={}))
            history = folder / "history.json"
            history.write_text(json.dumps({"submissions": submissions}))
            app = create_app(dict(TESTING=True, DATABASE=str(folder / "db.sqlite"),
                                  HISTORY=str(history), DEEPSEEK_API_KEY=""))
            client = app.test_client()

            overview = client.get("/?month=all&department=IT")
            self.assertEqual(overview.status_code, 200)
            html = overview.get_data(as_text=True)
            for month in range(1, 7):
                self.assertIn(f'href="#month-{month}"', html)
                self.assertIn(f'id="month-{month}"', html)
            self.assertEqual(html.count("bar-red"), 1)
            self.assertEqual(html.count("bar-yellow"), 1)

            detail = client.get("/interns/DEMO-1?month=2&department=IT&overview_month=all")
            self.assertEqual(detail.status_code, 200)
            self.assertIn('month=all&amp;department=IT#interns', detail.get_data(as_text=True))
