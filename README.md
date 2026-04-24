# Project Law (CaseMatch benzeri MVP)

İngiltere & Galler **Find Case Law** (National Archives) verisi üzerinde **anlamsal arama** yapan, isteğe bağlı **LLM özet** ve “neden benzer” metni üreten küçük bir yığın: **FastAPI** + **PostgreSQL + pgvector** + lokal **BGE (FastEmbed)** + OpenAI-uyumlu **OpenAI API / OpenRouter**.

Bu yazılım **hukukî tavsiye değildir**. Tüm metinler kaynak hükimle birlikte doğrulanmalıdır.

## Özellikler

- Atom feed’den dava listesi, `data.xml` ile hükmet metni çekme (ingestion CLI).
- Metin parçalama, **384 boyut** embedding (`BAAI/bge-small-en-v1.5`), `case_chunks` tablosunda saklama.
- `POST /v1/search` ile sorgu embedding’i + pgvector yakın komşu + (isteğe) LLM ile sıralama/özet.
- Tek sayfa arayüz: `app/static/index.html`

## Gereksinimler

- **Python 3.11+** (3.13 ile test edildi; torch gerekmez).
- **PostgreSQL 14+** ve **pgvector** eklentisi.
- (İsteğe) **OpenAI** veya **OpenRouter** API anahtarı (özet/LLM adımı için).

## Kurulum

```bash
cd project_law
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Veritabanı migrasyonları

```bash
psql -d project_law -f db/migrations/001_init.sql
psql -d project_law -f db/migrations/002_ingestion_hybrid_embedding.sql
```

`002` , `vector(384)` ve `ingestion_runs` / `search_events` tablolarını ekler. İlk kez `001` çalıştıysanız, `002` mevcut `case_chunks` tablosunu boyut uyuşması için yeniden oluşturur (dikkat: eski vektörler silinir).

## Ortam değişkenleri

Kökte `.env` oluşturun (`.env.example` referans; `.env` asla commit etmeyin).

| Değişken | Açıklama |
|----------|----------|
| `DATABASE_URL` | Örn. `postgresql://KULLANICI@localhost:5432/project_law` |
| `OPENAI_API_KEY` | OpenAI `sk-...` veya OpenRouter `sk-or-...` |
| `LLM_SERVICE_URL` | OpenRouter: `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | Örn. `openai/gpt-4o-mini` |
| `PORT` | Uvicorn portu (varsayılan 8000) |
| `FCL_ATOM_BASE` | Find Case Law atom URL’si (varsayılan resmi) |
| `FCL_REQUEST_SLEEP` | API nezaketi için istek arası gecikme (saniye) |
| `SEARCH_CANDIDATE_K` / `SEARCH_FINAL_N` | Aday ve dönüş adedi |

## Veri indirme (ingestion)

```bash
source .venv/bin/activate
cd project_law
# Örnek: 100 yeni, veritabanında olmayan dava; gerekirse 25 feed sayfasına kadar ilerle
python -m app.cli ingest --limit 100 --pages 25
```

- `--limit`: **sadece veritabanında olmayan** kaç dava eklensin (varsayılan: 30). Aynı `source_uri` mükerrer satır açmaz; zaten `cases` tablosundaki URI’lar atlanır, feed ileri sayfalara devam eder.
- `--pages`: En fazla kaç Atom sayfası gezilecek; yeterli yeni dava toplanamadıysa değerini artır.
- `--include-existing`: Normalde dışarıda. Verilirse, DB’de olsa bile feed’deki girdileri yeniden indirip metni/embed’i günceller.
- [Find Case Law](https://caselaw.nationalarchives.gov.uk) her IP için dakikada istek sınırı uygulayabilir; toplu indekslemede lisans/izin açısından [permissions](https://caselaw.nationalarchives.gov.uk/permissions-and-licensing) sayfasını inceleyin.

## API ve arayüzü çalıştırma

```bash
source .venv/bin/activate
cd project_law
uvicorn app.main:app --host 127.0.0.1 --port 8000
# veya (PORT ve .env ile):
python -m app
```

- Sağlık: `http://127.0.0.1:8000/health`
- Arayüz: `http://127.0.0.1:8000/`
- OpenAPI: `http://127.0.0.1:8000/docs`

### Örnek sorgu

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"unfair dismissal whistleblowing UK","final_n":5,"candidate_k":40}'
```

Yanıtta `used_llm: true` ise LLM adımı çalışmıştır. Anahtar yoksa sadece embedding + sabit açıklama metinleri döner.

## Mimari özet

1. Ingest: Atom → hükmet XML → düz metin → chunk → FastEmbed vektör → PostgreSQL.  
2. Arama: sorgu embedding’i → pgvector ile aday parçalar → (isteğe) LLM ile özet/“neden benzer”.

## Lisans (yazılım)

Bu repodaki uygulama kodu proje tercihinize bırakılmıştır; hükmet metinleri **National Archives / Open Justice** koşullarına tabidir.

## Sorun giderme

- **`curl: (7) connection refused`**: Uvicorn çalışmıyor veya `PORT` yanlış.  
- **“Set OPENAI_API_KEY...” / `used_llm: false`**: `.env`’de `OPENAI_API_KEY` (ve OpenRouter için `LLM_SERVICE_URL`) eksik; sunucuyu yeniden başlatın.  
- **Embedding boyutu hatası**: `app/embedding_model.py` ile `db/migrations/002_*` içindeki `vector(384)` tutarlı olmalı.  
- `get_settings` önbelleği: proses yeniden başlatılmadıkça eski env okunabilir.

---

**Güvenlik:** API anahtarlarını repoya, sohbetlere veya ekran görüntülerine koymayın. OpenRouter/ OpenAI panellerinde düzenli key rotasyonu uygulayın.
