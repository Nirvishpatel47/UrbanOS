import resend
from Security.Advance_Logger import logger
from Security.get_secretes import load_env_from_secret

async def send_escalation_email(message: str, receiver_email: str) -> bool:
    try:
        resend.api_key = load_env_from_secret("RESEND_API_KEY")

        if not resend.api_key or not receiver_email:
            logger.error("Resend API key or receiver email missing")
            return False

        subject = f"Message from UrbanOS"

        html_body = f"""
        <h2>From UrbanOS</h2>
        
        <h3>Message:</h3>
        <p>{message}</p>
        """

        params = {
            "from": "onboarding@resend.dev", # ← Change this to your verified domain
            "to": [receiver_email],
            "subject": subject,
            "html": html_body,
        }

        email = resend.Emails.send(params)
        logger.info(f"Escalation email sent successfully. ID: {email.get('id')}")
        return True

    except Exception as e:
        logger.error("Failed to send escalation email via Resend", e)
        return False