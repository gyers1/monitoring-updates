"""
이메일 알림 서비스
"""

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import get_settings
from domain import Article, INotifier


class EmailNotifier(INotifier):
    """이메일 알림 발송"""
    
    def __init__(self):
        settings = get_settings()
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.email_from = settings.email_from
        self.email_to = settings.email_to
    
    async def notify(self, articles: list[Article], subject: str = "") -> bool:
        """키워드 매칭 게시글 이메일 알림"""
        if not articles:
            return True
        
        if not self.smtp_host or not self.email_to:
            print("[WARN] No email settings. Skipping notification.")
            return False
        
        if not subject:
            subject = f"[모니터링 알림] 새 게시글 {len(articles)}건"
        
        # HTML 본문 생성
        body = self._build_html_body(articles)
        
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.email_from or self.smtp_user
            msg["To"] = self.email_to
            
            msg.attach(MIMEText(body, "html", "utf-8"))
            
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=True,
            )
            
            print(f"[EMAIL] Sent: {len(articles)} articles")
            return True
            
        except Exception as e:
            print(f"[ERROR] Email failed: {e}")
            return False
    
    def _build_html_body(self, articles: list[Article]) -> str:
        """HTML 본문 생성"""
        rows = ""
        for a in articles:
            rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{a.site_name}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">
                    <a href="{a.url}" style="color: #1a73e8;">{a.title}</a>
                </td>
            </tr>
            """
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body style="font-family: 'Malgun Gothic', sans-serif; padding: 20px;">
            <h2 style="color: #333;">📊 새 게시글 알림</h2>
            <p>아래 게시글이 새로 등록되었습니다.</p>
            <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                <thead>
                    <tr style="background: #f5f5f5;">
                        <th style="padding: 12px; text-align: left; width: 150px;">출처</th>
                        <th style="padding: 12px; text-align: left;">제목</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
            <p style="color: #666; font-size: 12px; margin-top: 20px;">
                이 메일은 자동 발송되었습니다.
            </p>
        </body>
        </html>
        """
