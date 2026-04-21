# -*- coding:utf-8 -*-
import smtplib
import email
import time
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

class EmailSender:
    """
    A class to send emails with retry mechanism.

    Can send plain text or HTML emails. HTML can be provided as a string
    or from a local file.
    """

    def __init__(self, smtp_host, smtp_port, username, password, use_ssl=False, use_tls=True, max_retries=3, retry_delay=5):
        """
        Initializes the EmailSender.

        Args:
            smtp_host (str): The SMTP server host.
            smtp_port (int): The SMTP server port.
            username (str): The email account username for authentication.
            password (str): The email account password for authentication.
            use_ssl (bool): Whether to use SMTP_SSL. Defaults to False.
            use_tls (bool): Whether to use STARTTLS. Defaults to True.
            max_retries (int): The maximum number of times to retry sending.
            retry_delay (int): The delay in seconds between retries.
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.use_tls = use_tls
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _send(self, msg):
        """
        Internal method to connect and send the email message.
        """
        client = None
        try:
            if self.use_ssl:
                client = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
                # ctxt = ssl.create_default_context()
                # ctxt.set_ciphers('DEFAULT')
                # client = smtplib.SMTP_SSL('smtp.qiye.aliyun.com', 465, context=ctxt)
            else:
                client = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
                if self.use_tls:
                    client.starttls()
            
            client.login(self.username, self.password)
            
            # The 'To' header can be a comma-separated string, but sendmail needs a list of addresses.
            # We get this from the message object's 'To', 'Cc', and 'Bcc' fields.
            receivers = [addr for field in ('To', 'Cc', 'Bcc') if msg[field] for addr in msg[field].split(',')]
            
            client.sendmail(self.username, receivers, msg.as_string())
            print("Successfully sent email.")
            return True
        except smtplib.SMTPException as e:
            print(f"Failed to send email: {e}")
            return False
        finally:
            if client:
                client.quit()

    def send_email(self, to_addrs, subject, body_html=None, body_text=None, from_alias="Genius AI", cc_addrs=None, bcc_addrs=None, reply_to=None):
        """
        Sends an email with retry logic.

        Args:
            to_addrs (list): A list of recipient email addresses.
            subject (str): The subject of the email.
            body_html (str, optional): The HTML content of the email.
            body_text (str, optional): The plain text content of the email.
            from_alias (str, optional): The display name for the sender.
            cc_addrs (list, optional): A list of CC recipient email addresses.
            bcc_addrs (list, optional): A list of BCC recipient email addresses.
            reply_to (str, optional): The reply-to email address.

        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        if not body_html and not body_text:
            raise ValueError("Either body_html or body_text must be provided.")

        msg = MIMEMultipart('alternative')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = formataddr((from_alias, self.username))
        msg['To'] = ", ".join(to_addrs)
        if cc_addrs:
            msg['Cc'] = ", ".join(cc_addrs)
        if bcc_addrs:
            # BCC addresses are not included in the headers
            pass
        if reply_to:
            msg['Reply-to'] = reply_to
        
        msg['Message-id'] = email.utils.make_msgid()
        msg['Date'] = email.utils.formatdate()

        if body_text:
            msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        if body_html:
            msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        for attempt in range(self.max_retries):
            print(f"Sending email... Attempt {attempt + 1}/{self.max_retries}")
            if self._send(msg):
                return True
            if attempt < self.max_retries - 1:
                print(f"Retrying in {self.retry_delay} seconds...")
                time.sleep(self.retry_delay)
        
        print("Failed to send email after all retries.")
        return False

    def send_html_from_file(self, to_addrs, subject, file_path, **kwargs):
        """
        Sends an email with HTML content from a file.

        Args:
            to_addrs (list): A list of recipient email addresses.
            subject (str): The subject of the email.
            file_path (str): The path to the HTML file.
            **kwargs: Additional arguments for send_email.

        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            return self.send_email(to_addrs, subject, body_html=html_content, **kwargs)
        except FileNotFoundError:
            print(f"Error: HTML file not found at {file_path}")
            return False
        except Exception as e:
            print(f"Error reading HTML file: {e}")
            return False

# if __name__ == '__main__':
    # Example Usage:
    # Replace with your actual SMTP credentials and settings
    
    # SENDER_USERNAME = "ai.public@comlan.com"
    # SENDER_PASSWORD = "Aa@#$250917" # It's recommended to use environment variables or a config file
    # SMTP_HOST = "mail.comlan.com"
    # SMTP_PORT = 25 # or 465 for SSL, 587 for TLS

    # SENDER_USERNAME = "bo.wang@playpro.cn"
    # SENDER_PASSWORD = "!@#qwe123qwe" # It's recommended to use environment variables or a config file
    # SMTP_HOST = "smtp.qiye.aliyun.com"
    # SMTP_PORT = 465 # or 465 for SSL, 587 for TLS

    # # Initialize the sender
    # # For non-SSL on port 25 with STARTTLS
    # email_sender = EmailSender(
    #     smtp_host=SMTP_HOST,
    #     smtp_port=SMTP_PORT,
    #     username=SENDER_USERNAME,
    #     password=SENDER_PASSWORD,
    #     # use_ssl=False,
    #     # use_tls=True,
    #     use_ssl=True,
    #     use_tls=False,
    #     max_retries=3,
    #     retry_delay=10
    # )

    # --- Send a plain text email ---
    # print("--- Sending Plain Text Email ---")
    # success_text = email_sender.send_email(
    #     to_addrs=["bo.wang@comlan.com"],
    #     subject="Test Plain Text Email from EmailSender",
    #     body_text="This is a test email sent using the EmailSender class."
    # )
    # print(f"Plain text email sent successfully: {success_text}\n")

    # --- Send an HTML email from a string ---
    # print("--- Sending HTML Email from String ---")
    # html_string = "<h1>HTML Email</h1><p>This is a test HTML email from a <strong>string</strong>.</p>"
    # success_html_string = email_sender.send_email(
    #     to_addrs=["bo.wang@comlan.com"],
    #     subject="Test HTML Email from String",
    #     from_alias="PLAYPRO AI",
    #     body_html=html_string,
    #     body_text="This is the plain text fallback for the HTML email." # Good practice
    # )
    # print(f"HTML (from string) email sent successfully: {success_html_string}\n")

    # # --- Send an HTML email from a file ---
    # print("--- Sending HTML Email from File ---")
    # # Create a dummy html file for testing
    # HTML_FILE = 'test/新闻简报_GDPVal finding Claude Opus 41 within 95 of AGI human experts in top 44 white collar jobs.html'
    
    # success_html_file = email_sender.send_html_from_file(
    #     to_addrs=["bo.wang@comlan.com"],
    #     subject="HTML Email from File",
    #     file_path=HTML_FILE,
    #     body_text="This is the plain text fallback for the HTML email from file." # Good practice
    # )
    # print(f"HTML (from file) email sent successfully: {success_html_file}")