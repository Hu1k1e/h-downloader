from backend.database import SessionLocal
from backend.models import DownloadJob

session = SessionLocal()
job = session.query(DownloadJob).filter(DownloadJob.title.ilike("%Spa%")).first()
if job:
    print(f"Title: {job.title}")
    print(f"Blacklisted: {job.blacklisted_urls}")
    
    # Let's clear the blacklist to fix it!
    job.blacklisted_urls = ""
    session.commit()
    print("Cleared blacklist for Spa!")
else:
    print("Not found in DB")
