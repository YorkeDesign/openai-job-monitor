#!/usr/bin/env python3
"""
OpenAI Job Monitor - Enhanced with CV Matching and Job Scoring
Monitors OpenAI jobs via Ashby API, tracks job status, and scores matches against CV
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
from job_matcher import JobMatcher

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
    """Monitor OpenAI jobs using Ashby's public API with lifecycle tracking and CV matching"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.api_url = "https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=true"
        self.data_dir = Path("job_data")
        self.data_dir.mkdir(exist_ok=True)
        
        # Initialize job matcher
        self.job_matcher = JobMatcher(config.get('profile_path', 'profile.json'))
        
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
                # Existing job - update it but preserve match analysis
                existing_job = db_jobs_by_url[job_url]
                match_analysis = existing_job.get('match_analysis')  # Preserve existing analysis
                
                existing_job.update(job)  # Update with latest data
                existing_job['status'] = 'ACTIVE'
                existing_job['last_seen'] = current_date.isoformat()
                
                # Restore match analysis if it existed
                if match_analysis:
                    existing_job['match_analysis'] = match_analysis
                
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
    
    def analyze_new_jobs(self, new_jobs: List[Dict]) -> List[Dict]:
        """Analyze new jobs for CV matching"""
        if not new_jobs:
            return []
        
        logger.info(f"Analyzing {len(new_jobs)} new jobs for CV matching...")
        
        if self.config.get('enable_cv_matching', True):
            analyzed_jobs = self.job_matcher.batch_analyze_jobs(new_jobs)
            
            # Update database with match analysis
            database = self.load_job_database()
            for analyzed_job in analyzed_jobs:
                # Find and update the job in database
                for db_job in database:
                    if db_job['jobUrl'] == analyzed_job['jobUrl']:
                        db_job['match_analysis'] = analyzed_job['match_analysis']
                        break
            
            self.save_job_database(database)
            return analyzed_jobs
        else:
            logger.info("CV matching disabled in config")
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
                        compensation_info['salary_max']
