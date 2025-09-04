#!/usr/bin/env python3
"""
OpenAI Job Monitor - Clean API-based Solution
Monitors OpenAI jobs via Ashby API and reports new listings in San Francisco area
"""

import requests
import json
import csv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import schedule
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('openai_jobs.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class OpenAIJobMonitor:
    """Monitor OpenAI jobs using Ashby's public API"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.api_url = "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true"
        self.data_dir = Path("job_data")
        self.data_dir.mkdir(exist_ok=True)
        
        # Files for tracking
        self.current_jobs_file = self.data_dir / "current_openai_jobs.json"
        self.report_file = self.data_dir / f"openai_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        self.csv_file = self.data_dir / f"openai_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    def fetch_jobs(self) -> Optional[List[Dict]]:
        """Fetch current jobs from OpenAI's Ashby API"""
        try:
            logger.info("Fetching jobs from OpenAI Ashby API...")
            response = requests.get(self.api_url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            jobs = data.get('jobs', [])
            
            logger.info(f"Successfully fetched {len(jobs)} jobs from API")
            return jobs
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch jobs from API: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse API response: {e}")
            return None
    
    def filter_san_francisco_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Filter jobs for San Francisco area"""
        sf_keywords = ['san francisco', 'sf', 'bay area']
        sf_jobs = []
        
        for job in jobs:
            # Check primary location
            location = job.get('location', '').lower()
            if any(keyword in location for keyword in sf_keywords):
                sf_jobs.append(job)
                continue
            
            # Check secondary locations
            secondary_locations = job.get('secondaryLocations', [])
            for sec_loc in secondary_locations:
                sec_location = sec_loc.get('location', '').lower()
                if any(keyword in sec_location for keyword in sf_keywords):
                    sf_jobs.append(job)
                    break
            
            # Check if job is remote (could be relevant)
            if job.get('isRemote', False) and 'remote' in self.config.get('include_remote', []):
                sf_jobs.append(job)
        
        logger.info(f"Filtered to {len(sf_jobs)} San Francisco area jobs")
        return sf_jobs
    
    def identify_new_jobs(self, current_jobs: List[Dict]) -> List[Dict]:
        """Identify new jobs since last check"""
        if not self.current_jobs_file.exists():
            # First run - all jobs are "new" but we'll only report recent ones
            logger.info("First run - checking for recently published jobs")
            cutoff_date = datetime.now() - timedelta(days=self.config.get('first_run_days', 7))
            
            new_jobs = []
            for job in current_jobs:
                published_at = datetime.fromisoformat(job['publishedAt'].replace('Z', '+00:00'))
                if published_at.replace(tzinfo=None) > cutoff_date:
                    new_jobs.append(job)
            
            logger.info(f"Found {len(new_jobs)} jobs published in last {self.config.get('first_run_days', 7)} days")
            return new_jobs
        
        # Load previous jobs
        try:
            with open(self.current_jobs_file, 'r') as f:
                previous_jobs = json.load(f)
            
            previous_job_urls = {job['jobUrl'] for job in previous_jobs}
            new_jobs = [job for job in current_jobs if job['jobUrl'] not in previous_job_urls]
            
            logger.info(f"Found {len(new_jobs)} new jobs since last check")
            return new_jobs
            
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Could not load previous jobs file: {e}")
            # Fallback to date-based filtering
            return self.identify_new_jobs(current_jobs)
    
    def extract_compensation(self, job: Dict) -> Dict:
        """Extract and format compensation data from job posting"""
        compensation_info = {
            'salary_summary': '',
            'salary_range': '',
            'equity': '',
            'bonus': '',
            'full_compensation': ''
        }
        
        compensation = job.get('compensation', {})
        
        # Check if compensation data exists
        if not compensation or not compensation.get('compensationTierSummary'):
            logger.info(f"No compensation data for {job.get('title', 'Unknown')}")
            return compensation_info
        
        logger.info(f"Found compensation data for {job.get('title', 'Unknown')}")
        
        # Get human-readable summaries directly from API
        compensation_info['full_compensation'] = compensation.get('compensationTierSummary', '')
        compensation_info['salary_range'] = compensation.get('scrapeableCompensationSalarySummary', '')
        
        # Parse detailed compensation components for more granular data
        summary_components = compensation.get('summaryComponents', [])
        for component in summary_components:
            comp_type = component.get('compensationType', '')
            min_val = component.get('minValue')
            max_val = component.get('maxValue')
            currency = component.get('currencyCode', 'USD')
            
            if comp_type == 'Salary' and min_val and max_val:
                compensation_info['salary_summary'] = f"${min_val:,.0f} - ${max_val:,.0f} {currency}"
            elif comp_type == 'EquityPercentage' and min_val and max_val:
                compensation_info['equity'] = f"{min_val}% - {max_val}%"
            elif comp_type == 'EquityCashValue':
                compensation_info['equity'] = 'Offered'
            elif comp_type == 'Bonus':
                compensation_info['bonus'] = 'Yes' if min_val or max_val else 'Offered'
        
        return compensation_info
    
    def save_current_jobs(self, jobs: List[Dict]):
        """Save current job state for next comparison"""
        try:
            with open(self.current_jobs_file, 'w') as f:
                json.dump(jobs, f, indent=2)
            logger.info(f"Saved {len(jobs)} current jobs to {self.current_jobs_file}")
        except Exception as e:
            logger.error(f"Failed to save current jobs: {e}")
    
    def generate_report(self, new_jobs: List[Dict]) -> str:
        """Generate a human-readable report of new jobs"""
        if not new_jobs:
            return "No new OpenAI jobs found in San Francisco area."
        
        report_lines = [
            f"🚀 NEW OPENAI JOBS REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"{'='*60}",
            f"Found {len(new_jobs)} new job(s) in San Francisco area:",
            ""
        ]
        
        for i, job in enumerate(new_jobs, 1):
            published_date = datetime.fromisoformat(job['publishedAt'].replace('Z', '+00:00'))
            compensation = self.extract_compensation(job)
            
            report_lines.extend([
                f"{i}. {job['title']}",
                f"   📍 Location: {job['location']}",
                f"   🏢 Department: {job.get('department', 'N/A')}",
                f"   👥 Team: {job.get('team', 'N/A')}",
                f"   📅 Published: {published_date.strftime('%Y-%m-%d %H:%M:%S')}",
                f"   🌐 Remote: {'Yes' if job.get('isRemote') else 'No'}",
            ])
            
            # Add compensation info if available
            if compensation['full_compensation']:
                report_lines.append(f"   💰 Compensation: {compensation['full_compensation']}")
            elif compensation['salary_range']:
                report_lines.append(f"   💰 Salary: {compensation['salary_range']}")
            
            report_lines.extend([
                f"   🔗 Apply: {job['applyUrl']}",
                f"   📋 Details: {job['jobUrl']}",
                ""
            ])
            
            # Add secondary locations if any
            if job.get('secondaryLocations'):
                secondary_locs = [loc['location'] for loc in job['secondaryLocations']]
                report_lines.append(f"   📍 Also available in: {', '.join(secondary_locs)}")
                report_lines.append("")
        
        report = "\n".join(report_lines)
        
        # Save report to file
        try:
            with open(self.report_file, 'w') as f:
                f.write(report)
            logger.info(f"Report saved to {self.report_file}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")
        
        return report
    
    def save_to_csv(self, jobs: List[Dict]):
        """Save jobs data to CSV format"""
        if not jobs:
            logger.info("No jobs to save to CSV")
            return
        
        try:
            logger.info(f"Attempting to save {len(jobs)} jobs to CSV")
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Headers
                writer.writerow([
                    'Title', 'Location', 'Department', 'Team', 'Published', 
                    'Remote', 'Employment Type', 'Salary Range', 'Salary Min', 'Salary Max',
                    'Full Compensation', 'Equity', 'Bonus', 'Apply URL', 'Job URL'
                ])
                
                # Data rows
                for i, job in enumerate(jobs):
                    try:
                        published_date = datetime.fromisoformat(job['publishedAt'].replace('Z', '+00:00'))
                        
                        # Initialize compensation data with all required keys
                        comp = {
                            'salary_range': '',
                            'salary_min': '',
                            'salary_max': '', 
                            'full_compensation': '',
                            'equity': '',
                            'bonus': ''
                        }
                        
                        # Extract compensation if available
                        compensation_data = job.get('compensation', {})
                        if compensation_data and compensation_data.get('compensationTierSummary'):
                            full_comp_raw = compensation_data.get('compensationTierSummary', '')
                            # Fix UTF-8 encoding issues - replace problematic characters
                            comp['full_compensation'] = (full_comp_raw
                                .replace('–', '-')           # em dash to hyphen
                                .replace('—', '-')           # en dash to hyphen  
                                .replace('•', '•')           # bullet point
                                .replace('\u2013', '-')     # unicode en dash
                                .replace('\u2014', '-')     # unicode em dash
                                .replace('\u2022', '•')     # unicode bullet
                                .encode('ascii', 'ignore').decode('ascii'))  # remove any remaining non-ASCII
                            comp['salary_range'] = compensation_data.get('scrapeableCompensationSalarySummary', '')
                            
                            # Parse salary components
                            summary_components = compensation_data.get('summaryComponents', [])
                            for component in summary_components:
                                if component.get('compensationType') == 'Salary':
                                    min_val = component.get('minValue')
                                    max_val = component.get('maxValue')
                                    if min_val:
                                        comp['salary_min'] = str(int(min_val))
                                    if max_val:
                                        comp['salary_max'] = str(int(max_val))
                                    # If only one value, use it for both min and max
                                    if min_val and not max_val:
                                        comp['salary_max'] = str(int(min_val))
                                    elif max_val and not min_val:
                                        comp['salary_min'] = str(int(max_val))
                                elif component.get('compensationType') == 'EquityCashValue':
                                    comp['equity'] = 'Offered'
                        
                        logger.info(f"Processing job {i+1}: {job.get('title', 'Unknown')} - Min: {comp['salary_min']}, Max: {comp['salary_max']}")
                        
                        writer.writerow([
                            job['title'],
                            job['location'],
                            job.get('department', ''),
                            job.get('team', ''),
                            published_date.strftime('%Y-%m-%d %H:%M:%S'),
                            'Yes' if job.get('isRemote') else 'No',
                            job.get('employmentType', ''),
                            comp['salary_range'],
                            comp['salary_min'],
                            comp['salary_max'],
                            comp['full_compensation'],
                            comp['equity'],
                            comp['bonus'],
                            job['applyUrl'],
                            job['jobUrl']
                        ])
                    except Exception as e:
                        logger.error(f"Error processing job {i+1} ({job.get('title', 'Unknown')}): {e}")
                        continue
            
            logger.info(f"CSV data saved to {self.csv_file}")
        except Exception as e:
            logger.error(f"Failed to save CSV: {e}")
    
    def send_email_notification(self, report: str, new_jobs: List[Dict]):
        """Send email notification if new jobs found"""
        if not new_jobs or not self.config.get('email_enabled'):
            return
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.config['email_from']
            msg['To'] = self.config['email_to']
            msg['Subject'] = f"🚀 {len(new_jobs)} New OpenAI Job(s) in San Francisco - {datetime.now().strftime('%Y-%m-%d')}"
            
            msg.attach(MIMEText(report, 'plain'))
            
            # Attach CSV if requested
            if self.config.get('attach_csv') and self.csv_file.exists():
                with open(self.csv_file, 'r') as f:
                    attachment = MIMEText(f.read(), 'csv')
                    attachment.add_header('Content-Disposition', 'attachment', filename=self.csv_file.name)
                    msg.attach(attachment)
            
            # Send email
            server = smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port'])
            server.starttls()
            server.login(self.config['email_from'], self.config['email_password'])
            server.send_message(msg)
            server.quit()
            
            logger.info("Email notification sent successfully")
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
    
    def run_check(self):
        """Main method to run a job check"""
        logger.info("Starting OpenAI job check...")
        
        # Fetch current jobs
        all_jobs = self.fetch_jobs()
        if all_jobs is None:
            logger.error("Failed to fetch jobs, aborting check")
            return
        
        # Filter for San Francisco
        sf_jobs = self.filter_san_francisco_jobs(all_jobs)
        
        # Identify new jobs
        new_jobs = self.identify_new_jobs(sf_jobs)
        
        # Generate report
        report = self.generate_report(new_jobs)
        print(report)
        
        # Save data
        if new_jobs:
            self.save_to_csv(new_jobs)
            self.send_email_notification(report, new_jobs)
        
        # Always save current state for next comparison
        self.save_current_jobs(sf_jobs)
        
        logger.info("Job check completed")
    
    def start_scheduler(self):
        """Start the scheduled monitoring"""
        check_time = self.config.get('check_time', '09:00')
        schedule.every().day.at(check_time).do(self.run_check)
        
        logger.info(f"Scheduler started - will check for new jobs daily at {check_time}")
        
        while True:
            schedule.run_pending()
            time.sleep(60)

def load_config(config_file: str = "config.json") -> Dict:
    """Load configuration from JSON file"""
    default_config = {
        "email_enabled": False,
        "email_from": "",
        "email_to": "",
        "email_password": "",
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "check_time": "09:00",
        "first_run_days": 7,
        "include_remote": [],  # Add "remote" to include remote jobs
        "attach_csv": True
    }
    
    if Path(config_file).exists():
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
            default_config.update(user_config)
        except Exception as e:
            logger.warning(f"Could not load config file: {e}")
    
    return default_config

def create_sample_config():
    """Create a sample configuration file"""
    sample_config = {
        "email_enabled": False,
        "email_from": "your_email@gmail.com",
        "email_to": "recipient@gmail.com", 
        "email_password": "your_app_password",
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "check_time": "09:00",
        "first_run_days": 7,
        "include_remote": [],
        "attach_csv": True
    }
    
    with open("config_sample.json", 'w') as f:
        json.dump(sample_config, f, indent=2)
    
    print("Sample configuration created as 'config_sample.json'")
    print("Copy to 'config.json' and customize as needed.")

def main():
    parser = argparse.ArgumentParser(description='OpenAI Job Monitor')
    parser.add_argument('--run-once', action='store_true', help='Run once and exit')
    parser.add_argument('--create-config', action='store_true', help='Create sample config file')
    parser.add_argument('--config', default='config.json', help='Config file path')
    
    args = parser.parse_args()
    
    if args.create_config:
        create_sample_config()
        return
    
    config = load_config(args.config)
    monitor = OpenAIJobMonitor(config)
    
    if args.run_once:
        monitor.run_check()
    else:
        monitor.start_scheduler()

if __name__ == "__main__":
    main()
