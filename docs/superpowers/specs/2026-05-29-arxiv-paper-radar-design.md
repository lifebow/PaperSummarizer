# arXiv Paper Radar - Design

**Date:** 2026-05-29  
**Status:** Approved for spec review  
**Project:** Standalone tool in `newpapers`

## Muc Tieu

Xay mot tool rieng le chay nhu daemon de theo doi arXiv hang gio, tap trung vao
`cs.AI` va cac chu de `LLM agent`, `AI safety`, `AI jailbreak`. Tool phat hien
paper moi, loc bot nhieu, tai PDF tam thoi, extract noi dung paper, dung LLM de
tao summary co nen tang kien thuc, QA lai chat luong, ghi digest Markdown theo
ngay, va gui Telegram daily recap luc 21:00 theo gio Viet Nam.

Muc tieu chinh la collect idea dua tren paper moi public, khong phai build mot
paper database lon hay dashboard web trong version dau.

## Quyet Dinh Chinh

- Tool moi nam trong `/Users/lifebow/Documents/arxiv_clone/newpapers`, khong phu
  thuoc code `paper_finding`.
- Process chay lien tuc nhu daemon, tu ngu va lap lai moi 60 phut.
- Ket qua doc chinh la Markdown digest theo ngay: `digests/YYYY-MM-DD.md`.
- SQLite la state store chinh de dedupe, track status, luu scores, summary, QA
  result, va trang thai Telegram recap.
- Telegram khong ping moi gio. Bot chi gui daily recap luc 21:00
  `Asia/Ho_Chi_Minh`.
- LLM co the dung thoai mai token. Pipeline uu tien chat luong va grounding hon
  tiet kiem token.
- Semantic Scholar duoc dung nhu fast prefilter/enrichment layer de giam latency
  va so request can goi sang arXiv. arXiv/paperscraper van la freshness
  authority de bat paper moi public ma Semantic Scholar co the chua index kip.
- PDF chi la temporary artifact. Sau khi extract/summarize/QA xong, xoa PDF de
  tranh ton storage. Cleanup chay trong moi duong thanh cong va loi.

## Luong Xu Ly

Moi vong hourly daemon:

```text
sleep until next run
  -> fetch recent candidates from Semantic Scholar
  -> reconcile with a small arXiv freshness pass
  -> dedupe against SQLite
  -> metadata/abstract relevance filter
  -> download PDF to data/tmp_pdfs/
  -> extract full paper text/Markdown
  -> LLM full-paper summary
  -> LLM QA gate
  -> write accepted papers to SQLite
  -> append accepted papers to digests/YYYY-MM-DD.md
  -> delete temporary PDF
  -> continue on per-paper errors
```

Moi ngay luc 21:00:

```text
read today's accepted papers from SQLite
  -> render compact Telegram recap
  -> send to Telegram bot/chat
  -> mark recap sent in SQLite if successful
```

## Retrieval

Retrieval duoc tach thanh interface rieng:

- `PaperSource.search_recent(config) -> list[PaperMetadata]`
- `PdfDownloader.download(paper, tmp_dir) -> Path`

Implementation mac dinh dung hybrid retrieval:

1. Semantic Scholar Graph API la fast prefilter/enrichment layer. Moi hourly run
   goi bulk/search theo cac query topic, gioi han fields toi thieu nhu
   `title`, `abstract`, `publicationDate`, `externalIds`, `openAccessPdf`,
   `tldr`, `fieldsOfStudy`, `url`. Paper khong co `externalIds.ArXiv` bi bo qua
   trong version dau de giu scope arXiv-only.
2. arXiv/paperscraper la freshness authority. Moi hourly run van chay mot pass
   nho tren arXiv theo `cs.AI` va moc thoi gian gan day de bat paper vua public
   ma Semantic Scholar co the chua index kip.
3. Metadata tu hai nguon duoc merge bang arXiv id. Neu co conflict, arXiv id,
   title, published/updated date tu arXiv duoc uu tien cho freshness; abstract,
   TLDR, citation/open-access metadata tu Semantic Scholar duoc dung de enrich.

`paperscraper` van duoc dung cho arXiv search/PDF retrieval, vi thu vien nay da
ho tro metadata va full-text/PDF retrieval. Neu `paperscraper` khong lay duoc
PDF arXiv, fallback ve URL chuan:

```text
https://arxiv.org/pdf/<arxiv_id>.pdf
```

Search ban dau tap trung vao `cat:cs.AI` ket hop cac topic query:

- `LLM agent`
- `AI safety`
- `AI jailbreak`

Moi hourly run chi xu ly paper moi hon moc `last_successful_fetch_at` trong
SQLite. Lan dau tien mac dinh look back 48 gio de khong bo sot paper moi gan
day, nhung van bi gioi han boi `max_papers_per_batch`. Semantic Scholar co the
loc theo publication date de giam ket qua can xu ly; arXiv freshness pass dung
moc thoi gian rieng de bu vao indexing lag.

Version dau chi can arXiv. Cac source khac ma `paperscraper` ho tro co the them
sau bang cung interface.

## PDF Extraction

PDF duoc tai vao `data/tmp_pdfs/<safe_paper_id>.pdf`.

Extractor chinh:

- `PyMuPDF4LLM`: convert PDF thanh Markdown/LLM-ready text. Uu tien vi hop voi
  paper nhieu cot, heading, chunk theo page, va dau vao LLM.

Fallback:

- `pdfplumber`: dung khi PyMuPDF4LLM loi hoac extracted text qua ngan.

SQLite khong luu PDF. SQLite chi luu metadata extraction nhu:

- `extracted_text_chars`
- `extractor_name`
- `extraction_status`
- `extraction_error`

Full extracted text co the khong luu lau dai trong version dau de tranh phinh
database. Neu can debug, co the luu error va metadata, roi reprocess paper sau.

Cleanup PDF bat buoc chay trong `finally`, ke ca khi LLM hoac QA fail.

## Filtering Va QA Gate

Pipeline co hai tang chong spam.

### Tang 1: Candidate Filter

Chay truoc khi tai PDF:

- Paper phai la paper moi chua thay trong SQLite.
- Paper phai nam trong/gan `cs.AI`.
- Title/abstract phai co lien quan ro den mot trong cac topic.
- LLM relevance classifier doc title + abstract va tra JSON co diem/ly do.

Chi paper dat muc "balanced relevance" moi duoc tai PDF. Muc nay tranh qua rong
gay spam, nhung khong qua chat den muc bo sot paper co idea tot.

### Tang 2: Full-Paper QA Gate

Sau khi da extract full paper, LLM tao summary truoc, roi mot QA pass rieng cham:

- `relevance_score` tu 0 den 10
- `grounding_score` tu 0 den 10
- `idea_score` tu 0 den 10

Nguong mac dinh:

- `relevance_score >= 7`
- `grounding_score >= 7`
- `idea_score >= 6`

Paper chi vao digest neu vuot nguong tong hop. QA result phai gom ly do ngan va
evidence snippets tu abstract/full text de han che hallucination.

## LLM Summary Format

Moi paper duoc render theo hybrid research brief + idea mining. Bat buoc co cac
phan:

1. **Background needed**  
   Giai thich kien thuc nen tang can de hieu paper. Muc do mac dinh la
   "deep but concise": co intuition, ky hieu/cong thuc chinh neu paper dung toan,
   va vi sao phan nen tang do quan trong voi contribution.

2. **What the paper does**  
   Paper dang giai quyet bai toan gi va vi sao dang quan tam.

3. **Novelty / contribution**  
   Diem moi so voi cach lam/van de lien quan.

4. **Method**  
   Cach tiep can chinh, architecture/thuat toan/procedure neu co.

5. **Math / technical core**  
   Tom tat phan ky thuat quan trong. Neu paper co cong thuc, giai thich vai tro
   cua cong thuc bang truc giac, khong chi chep lai ky hieu.

6. **Results / claims**  
   Claim hoac ket qua chinh ma paper dua ra.

7. **Limitations / uncertainty**  
   Diem yeu, dieu chua ro, assumption, hoac phan can doc ky them.

8. **Ideas to try**  
   2-5 idea co the follow-up: research experiment, product angle, agent/prompt
   angle, safety evaluation, hoac implementation idea.

9. **QA scores and evidence**  
   Diem relevance/grounding/idea, ly do giu paper, va evidence snippets ngan.

LLM output nen la JSON structured truoc, sau do renderer bien thanh Markdown.

## Digest Markdown

Digest theo ngay nam o:

```text
digests/YYYY-MM-DD.md
```

Moi hourly batch append mot section co timestamp, vi du:

```markdown
## 15:00 Batch

### Paper Title

- arXiv: ...
- Link: ...
- Topics: ...
- QA: relevance 8 / grounding 8 / idea 7

...
```

Neu mot batch khong co paper dat QA, co the khong append gi vao digest de file
gon. Log van ghi vao SQLite.

## Telegram Recap

Telegram bot gui mot recap vao 21:00 `Asia/Ho_Chi_Minh` moi ngay.

Recap nen ngan hon Markdown digest:

- So paper duoc giu trong ngay
- Top papers theo idea score hoac relevance score
- Moi paper gom title, arXiv link, 1-2 dong "why it matters", va 1 idea noi bat
- Neu khong co paper dat QA trong ngay, bot co the gui mot thong bao ngan hoac im
  lang tuy config. Mac dinh: im lang.

Telegram token va chat id doc tu env hoac `.env`, khong hard-code vao repo.

Neu gui Telegram fail, digest va SQLite van duoc luu. Daemon ghi loi va retry o
lan recap ke tiep neu chua mark `sent`.

## SQLite Schema Du Kien

Bang `papers`:

- `id`
- `arxiv_id`
- `semantic_scholar_id`
- `title`
- `authors_json`
- `abstract`
- `semantic_scholar_tldr`
- `categories_json`
- `published_at`
- `updated_at`
- `pdf_url`
- `semantic_scholar_url`
- `source`
- `first_seen_at`
- `last_status`
- `last_error`

Bang `runs`:

- `id`
- `started_at`
- `finished_at`
- `status`
- `found_count`
- `accepted_count`
- `error_count`

Bang `paper_results`:

- `id`
- `paper_id`
- `run_id`
- `candidate_relevance_score`
- `extractor_name`
- `extracted_text_chars`
- `summary_json`
- `relevance_score`
- `grounding_score`
- `idea_score`
- `qa_reason`
- `accepted`
- `digest_date`
- `created_at`

Bang `telegram_recaps`:

- `id`
- `digest_date`
- `sent_at`
- `status`
- `error`

Schema co the toi gian lai luc implement, nhung phai giu du thong tin de dedupe,
rerun, va debug loi.

## Configuration

Tool co `config.yaml`:

```yaml
topics:
  categories: ["cs.AI"]
  queries:
    - "LLM agent"
    - "AI safety"
    - "AI jailbreak"

daemon:
  interval_minutes: 60
  timezone: "Asia/Ho_Chi_Minh"
  daily_recap_time: "21:00"

filters:
  max_papers_per_batch: 20
  relevance_threshold: 7
  grounding_threshold: 7
  idea_threshold: 6

paths:
  database: "data/paper_radar.sqlite3"
  tmp_pdfs: "data/tmp_pdfs"
  digests: "digests"

semantic_scholar:
  enabled: true
  api_key_env: "SEMANTIC_SCHOLAR_API_KEY"
  fields:
    - "title"
    - "abstract"
    - "publicationDate"
    - "externalIds"
    - "openAccessPdf"
    - "tldr"
    - "fieldsOfStudy"
    - "url"
  require_arxiv_external_id: true
  arxiv_freshness_reconciliation: true

llm:
  base_url_env: "OPENAI_BASE_URL"
  api_key_env: "OPENAI_API_KEY"
  model_env: "OPENAI_MODEL"

telegram:
  bot_token_env: "TELEGRAM_BOT_TOKEN"
  chat_id_env: "TELEGRAM_CHAT_ID"
```

Secrets nam trong env hoac `.env`, khong nam trong config committed.

## Error Handling

- Loi fetch/search: ghi run error, daemon tiep tuc vong sau.
- Loi mot paper: mark paper/result error, tiep tuc paper khac.
- Loi PDF download: khong retry vo han; ghi loi va co the retry o run sau.
- Loi extraction: thu fallback extractor; neu van fail thi mark error.
- Loi LLM: mark error, khong append digest.
- Loi Telegram: digest van ton tai, recap chua mark sent de retry sau.
- PDF temp cleanup chay bat buoc trong `finally`.

Daemon khong duoc chet vi loi cua mot paper.

## Testing

Test tap trung vao behavior co rui ro:

- Dedupe SQLite khong xu ly lai paper da thay.
- Semantic Scholar va arXiv merge cung mot paper bang `externalIds.ArXiv`.
- arXiv freshness pass van them duoc paper khi Semantic Scholar chua index kip.
- Candidate filter chi cho qua paper dat topic/relevance.
- PDF lifecycle: file PDF temp bi xoa sau success va sau error.
- Extractor fallback: PyMuPDF4LLM fail thi dung pdfplumber.
- QA threshold: chi accepted paper moi vao digest.
- Digest renderer tao Markdown dung structure.
- Telegram sender dung payload mong doi voi mock HTTP.
- Daemon scheduling tinh dung 60 phut va daily recap 21:00 Asia/Ho_Chi_Minh.

## Non-Goals Version Dau

- Khong lam web dashboard.
- Khong giu PDF lau dai.
- Khong can multi-source ngoai arXiv ngay tu dau.
- Khong can vector database/RAG search lich su trong version dau.
- Khong can gui Telegram hourly alert.

## Cau Hinh Mac Dinh Da Chot

- Source: hybrid Semantic Scholar + arXiv, category `cs.AI`.
- Topics: `LLM agent`, `AI safety`, `AI jailbreak`.
- Storage: SQLite + Markdown digest theo ngay.
- Daemon: tu chay lien tuc, interval 60 phut.
- Telegram: daily recap luc 21:00 gio Viet Nam.
- Retrieval: Semantic Scholar fast prefilter/enrichment, arXiv/paperscraper
  freshness authority, arXiv PDF URL fallback.
- Extraction: `PyMuPDF4LLM` primary, `pdfplumber` fallback.
- Summary: hybrid research brief + idea mining.
- Background: deep but concise, dac biet giai thich intuition toan/kien thuc nen
  neu paper can.
- QA: relevance + grounding + idea quality.
- PDF: xoa sau khi xu ly de tiet kiem storage.
