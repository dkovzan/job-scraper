from datetime import datetime

from models import Job
from scrapers.linkedin import _parse, fetch

SAMPLE_HTML = """
<li>
  <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:3812345678">
    <a class="base-card__full-link"
       href="https://www.linkedin.com/jobs/view/senior-ux-ui-designer-at-acme-3812345678?refId=abc&trackingId=xyz">
      <span class="sr-only">Senior UX/UI Designer</span>
    </a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title"> Senior UX/UI Designer </h3>
      <h4 class="base-search-card__subtitle"><a href="#">Acme Sp. z o.o.</a></h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">Warsaw, Mazowieckie, Poland</span>
        <time class="job-search-card__listdate" datetime="2026-05-28">2 days ago</time>
      </div>
    </div>
  </div>
</li>
<li>
  <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:3899999999">
    <a class="base-card__full-link"
       href="https://www.linkedin.com/jobs/view/product-designer-3899999999">
      <span class="sr-only">Product Designer</span>
    </a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title">Product Designer</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Beta Studio</a></h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">Poland (Remote)</span>
      </div>
    </div>
  </div>
</li>
"""


def test_parse_returns_jobs_with_correct_shape():
    jobs = _parse(SAMPLE_HTML)
    assert len(jobs) == 2
    for j in jobs:
        assert isinstance(j, Job)
        assert j.source == "linkedin.com"
        assert j.id.startswith("linkedin.com:")
        assert j.title
        assert j.company
        assert j.url.startswith("https://www.linkedin.com/jobs/view/")


def test_parse_extracts_first_card_fields():
    first = _parse(SAMPLE_HTML)[0]
    assert first.id == "linkedin.com:3812345678"
    assert first.title == "Senior UX/UI Designer"
    assert first.company == "Acme Sp. z o.o."
    assert first.url == "https://www.linkedin.com/jobs/view/senior-ux-ui-designer-at-acme-3812345678"
    assert first.salary is None
    assert first.posted_at == datetime(2026, 5, 28)
