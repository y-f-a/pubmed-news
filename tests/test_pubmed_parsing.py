from packages.pubmed.client import PubMedClient


def _sample_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>123</PMID>
      <Article>
        <ArticleTitle>Test <i>Title</i></ArticleTitle>
        <ArticleDate DateType="Electronic">
          <Year>2023</Year>
          <Month>11</Month>
          <Day>02</Day>
        </ArticleDate>
        <Abstract>
          <AbstractText Label="Background">Background text.</AbstractText>
          <AbstractText>Conclusion text.</AbstractText>
        </Abstract>
        <Journal>
          <Title>Test Journal</Title>
          <JournalIssue>
            <PubDate>
              <Year>2024</Year>
            </PubDate>
          </JournalIssue>
        </Journal>
        <AuthorList>
          <Author>
            <ForeName>Ada</ForeName>
            <LastName>Lovelace</LastName>
          </Author>
          <Author>
            <CollectiveName>Study Group</CollectiveName>
          </Author>
        </AuthorList>
      </Article>
      <PublicationTypeList>
        <PublicationType>Clinical Trial</PublicationType>
      </PublicationTypeList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1234/abc</ArticleId>
        <ArticleId IdType="pmc">12345</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>456</PMID>
      <Article>
        <ArticleTitle>Second Study</ArticleTitle>
        <Journal>
          <Title>Another Journal</Title>
          <JournalIssue>
            <PubDate>
              <MedlineDate>2022 Sep-Oct</MedlineDate>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parse_pubmed_xml_requires_abstract() -> None:
    client = PubMedClient(email="test@example.com")
    records = client._parse_pubmed_xml(_sample_xml(), require={"title": True, "abstract": True})
    assert len(records) == 1
    record = records[0]
    assert record["pmid"] == "123"
    assert record["title"] == "Test Title"
    assert record["journal"] == "Test Journal"
    assert record["year"] == "2024"
    assert record["publication_date"] == "2023-11-02"
    assert record["publication_date_raw"] == "2023-11-02"
    assert record["publication_date_source"] == "electronic_pub_date"
    assert record["doi"] == "10.1234/abc"
    assert record["pmcid"] == "PMC12345"
    assert record["authors"] == ["Ada Lovelace", "Study Group"]
    assert record["publication_types"] == ["Clinical Trial"]
    assert record["abstract"] == "Background: Background text.\nConclusion text."


def test_parse_pubmed_xml_allows_missing_abstract() -> None:
    client = PubMedClient(email="test@example.com")
    records = client._parse_pubmed_xml(_sample_xml(), require={"title": True, "abstract": False})
    pmids = {record["pmid"] for record in records}
    assert pmids == {"123", "456"}
    second = next(record for record in records if record["pmid"] == "456")
    assert second["year"] == "2022"
    assert second["publication_date"] == "2022-09"
    assert second["publication_date_raw"] == "2022 Sep-Oct"
    assert second["publication_date_source"] == "journal_issue_pub_date"
