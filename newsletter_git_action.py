from dotenv import load_dotenv
load_dotenv()

import os
from function.EmailSender import EmailSender
from function.NewsCollector import  NewsCollector

rss_url = os.getenv("RSS_URL")
subject, newsletter_html = NewsCollector().collect_news_job(rss_url=rss_url, send_email=False)
# subject = "Test Email from String"
# newsletter_html = "<h1>HTML Email</h1><p>This is a test HTML email from a <strong>string</strong>.</p>"
smtp_host = os.getenv("SMTP_HOST")
smtp_port = os.getenv("SMTP_PORT")
smtp_user = os.getenv("SENDER_USERNAME")
smtp_pass = os.getenv("SENDER_PASSWORD")
to_addrs_str = os.getenv("TO_ADDRS")
from_alias = os.getenv("FROM_ALIAS")

if not all([smtp_host, smtp_port, smtp_user, smtp_pass, to_addrs_str]):
    raise ValueError("One or more required SMTP or recipient settings are missing.")
recipients = [addr.strip() for addr in to_addrs_str.split(',') if addr.strip()]
# For non-SSL on port 25 with STARTTLS
email_sender = EmailSender(
    smtp_host=smtp_host,
    smtp_port=int(smtp_port),
    username=smtp_user,
    password=smtp_pass,
    # # Comlan
    # use_ssl=False,
    # use_tls=True,
    # Aliyun
    use_ssl=True,
    use_tls=False,
    max_retries=3,
    retry_delay=10
)

# --- Send an HTML email from a string ---
print("--- Sending HTML Email from String ---")
success_html_string = email_sender.send_email(
    to_addrs=recipients,
    subject=subject,
    from_alias=from_alias,
    body_html=newsletter_html
)