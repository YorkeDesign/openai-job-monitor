#!/usr/bin/env python3
"""
OpenAI Job Monitor - Enhanced with Job Lifecycle Tracking
Monitors OpenAI jobs via Ashby API and tracks job status over time
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
    """Monitor OpenAI jobs using Ashby's public API with lifecycle tracking"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.api_url = "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true"
        self.data_dir = Path("job_data")
        self.data_dir.mkdir(exist_ok=True)
        
        # Files for tracking
        self.current_jobs_file = self.data_dir / "current_openai_jobs.json"
        self.master_database_file = self.data_dir / "openai_jobs_database.json"
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
    
    def load_job_database(self) -> List[Dict]:
        """Load the master job database"""
        if not self.master_database_file.exists():
            return []
        
        try:
            with open(self.master_database_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load job database: {e}")
            return []
    
    def save_job_database(self, jobs: List[Dict]):
        """Save the master job database"""
        try:
            with open(self.master_database_file, 'w') as f:
                json.dump(jobs, f, indent=2)
            logger.info(f"Saved {len(jobs)} jobs to database")
        except Exception as e:
            logger.error(f"Failed to save job database: {e}")
    
    def update_job_database(self, current_sf_jobs: List[Dict]) -> List[Dict]:
        """Update the master database with job lifecycle tracking"""
        database = self.load_job_database()
        current_date = datetime.now()
        
        # Create lookup of current jobs by URL
        current_job_urls = {job['jobUrl'] for job in current_sf_jobs}
        
        # Create lookup of existing jobs in database
        db_jobs_by_url = {job['jobUrl']: job for job in database}
        
        new_jobs = []
        updated_database = []
        
        # Process current jobs from API
        for job in current_sf_jobs:
            job_url = job['jobUrl']
            
            if job_url in db_jobs_by_url:
                # Existing job - update it
                existing_job = db_jobs_by_url[job_url]
                existing_job.update(job)  # Update with latest data
                existing_job['status'] = 'ACTIVE'
                existing_job['last_seen'] = current_date.isoformat()
                
                # Calculate days since first listed
                first_seen = datetime.fromisoformat(existing_job['first_seen'])
                existing_job['days_since_listed'] = (current_date - first_seen).days
                
                updated_database.append(existing_job)
            else:
                # New job
                job['status'] = 'ACTIVE'
                job['first_seen'] = current_date.isoformat()
                job['last_seen'] = current_date.isoformat()
                job['days_since_listed'] = 0
                updated_database.append(job)
                new_jobs.append(job)
        
        # Process existing jobs that are no longer current (mark as CLOSED)
        for job in database:
            if job['jobUrl'] not in current_job_urls:
                if job['status'] == 'ACTIVE':
                    # Just became closed
                    job['status'] = 'CLOSED'
                    job['closed_date'] = current_date.isoformat()
                    logger.info(f"Job closed: {job['title']}")
                
                # Calculate days until deletion for closed jobs
                if job['status'] == 'CLOSED':
                    closed_date = datetime.fromisoformat(job['closed_date'])
                    days_closed = (current_date - closed_date).days
                    job['days_until_deletion'] = max(0, 5 - days_closed)
                    
                    # Only keep if within 5-day window
                    if days_closed < 5:
                        # Calculate days since first listed
                        first_seen = datetime.fromisoformat(job['first_seen'])
                        job['days_since_listed'] = (closed_date - first_seen).days
                        updated_database.append(job)
                    else:
                        logger.info(f"Job deleted: {job['title']} (closed for 5 days)")
        
        self.save_job_database(updated_database)
        return new_jobs
    
    def extract_compensation(self, job: Dict) -> Dict:
        """Extract and format compensation data from job posting"""
        compensation_info = {
            'salary_summary': '',
            'salary_range': '',
            'salary_min': '',
            'salary_max': '',
            'equity': '',
            'bonus': '',
            'full_compensation': ''
        }
        
        compensation = job.get('compensation', {})
        
        # Check if compensation data exists
        if not compensation or not compensation.get('compensationTierSummary'):
            return compensation_info
        
        try:
            # Get human-readable summaries directly from API - fix encoding issues
            full_comp_raw = compensation.get('compensationTierSummary', '')
            # Fix UTF-8 encoding issues - replace problematic characters
            compensation_info['full_compensation'] = (full_comp_raw
                .replace('–', '-')           # em dash to hyphen
                .replace('—', '-')           # en dash to hyphen  
                .replace('•', '•')           # bullet point
                .replace('\u2013', '-')     # unicode en dash
                .replace('\u2014', '-')     # unicode em dash
                .replace('\u2022', '•')     # unicode bullet
                .encode('ascii', 'ignore').decode('ascii'))  # remove any remaining non-ASCII
            compensation_info['salary_range'] = compensation.get('scrapeableCompensationSalarySummary', '')
            
            # Parse detailed compensation components for more granular data
            summary_components = compensation.get('summaryComponents', [])
            for component in summary_components:
                comp_type = component.get('compensationType', '')
                min_val = component.get('minValue')
                max_val = component.get('maxValue')
                currency = component.get('currencyCode', 'USD')
                
                if comp_type == 'Salary':
                    if min_val and max_val:
                        # Salary range
                        compensation_info['salary_summary'] = f"${min_val:,.0f} - ${max_val:,.0f} {currency}"
                        compensation_info['salary_min'] = str(int(min_val))
                        compensation_info['salary_max'] = str(int(max_val))
                    elif min_val and not max_val:
                        # Single salary value - put in both min and max
                        compensation_info['salary_summary'] = f"${min_val:,.0f} {currency}"
                        compensation_info['salary_min'] = str(int(min_val))
                        compensation_info['salary_max'] = str(int(min_val))
                    elif max_val and not min_val:
                        # Only max value (rare case)
                        compensation_info['salary_summary'] = f"Up to ${max_val:,.0f} {currency}"
                        compensation_info['salary_min'] = str(int(max_val))
                        compensation_info['salary_max'] = str(int(max_val))
                elif comp_type == 'EquityPercentage' and min_val and max_val:
                    compensation_info['equity'] = f"{min_val}% - {max_val}%"
                elif comp_type == 'EquityCashValue':
                    compensation_info['equity'] = 'Offered'
                elif comp_type == 'Bonus':
                    compensation_info['bonus'] = 'Yes' if min_val or max_val else 'Offered'
            
            return compensation_info
            
        except Exception as e:
            logger.error(f"ERROR in extract_compensation for {job.get('title')}: {e}")
            return compensation_info
    
    def save_current_jobs(self, jobs: List[Dict]):
        """Save current job state for backup"""
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
                            comp['full_compensation'] = (full_comp_raw
                                .replace('–', '-')           # em dash to hyphen
                                .replace('—', '-')           # en dash to hyphen  
                                .replace('•', '•')           # bullet point
                                .replace('\u2013', '-')     # unicode en dash
                                .replace('\u2014', '-')     # unicode em dash
                                .replace('\u2022', '•')     # unicode bullet
                                .encode('ascii', 'ignore').decode('ascii'))
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
    
    def generate_dashboard_data(self):
        """Generate JSON data file for the web dashboard"""
        database = self.load_job_database()
        
        # Separate active and closed jobs for dashboard
        active_jobs = [job for job in database if job['status'] == 'ACTIVE']
        closed_jobs = [job for job in database if job['status'] == 'CLOSED']
        
        dashboard_data = {
            'generated_at': datetime.now().isoformat(),
            'active_jobs': active_jobs,
            'closed_jobs': closed_jobs,
            'stats': {
                'total_active': len(active_jobs),
                'total_closed': len(closed_jobs),
                'departments': list(set(job.get('department', 'Unknown') for job in active_jobs)),
                'salary_ranges': [self.extract_compensation(job) for job in active_jobs if job.get('compensation')]
            }
        }
        
        # Save dashboard data
        dashboard_file = self.data_dir / "dashboard_data.json"
        try:
            with open(dashboard_file, 'w') as f:
                json.dump(dashboard_data, f, indent=2)
            logger.info(f"Dashboard data saved to {dashboard_file}")
        except Exception as e:
            logger.error(f"Failed to save dashboard data: {e}")
    
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
        
        # Update database and identify new jobs
        new_jobs = self.update_job_database(sf_jobs)
        
        # Generate report for new jobs only
        report = self.generate_report(new_jobs)
        print(report)
        
        # Generate dashboard data export
        self.generate_dashboard_data()
        
        # Save data and send notifications
        if new_jobs:
            self.save_to_csv(new_jobs)
            self.send_email_notification(report, new_jobs)
        
        # Always save current state for backup
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
