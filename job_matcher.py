#!/usr/bin/env python3
"""
Job Matcher - AI-powered CV matching and scoring for OpenAI jobs
Uses Claude API to analyze job descriptions against candidate profile
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import requests
import time
import re

logger = logging.getLogger(__name__)

class JobMatcher:
    """AI-powered job matching using Claude API"""
    
    def __init__(self, profile_path: str = "profile.json"):
        """Initialize with candidate profile"""
        self.profile_path = Path(profile_path)
        self.profile = self.load_profile()
        self.api_url = "https://api.anthropic.com/v1/messages"
        
    def load_profile(self) -> Dict:
        """Load candidate profile from JSON file"""
        try:
            if not self.profile_path.exists():
                logger.warning(f"Profile file {self.profile_path} not found. Create it with your CV data.")
                return {}
            
            with open(self.profile_path, 'r') as f:
                profile = json.load(f)
            logger.info(f"Loaded profile for {profile.get('personal_info', {}).get('name', 'Unknown')}")
            return profile
        except Exception as e:
            logger.error(f"Failed to load profile: {e}")
            return {}
    
    def analyze_job_match(self, job: Dict) -> Dict:
        """Analyze how well a job matches the candidate profile"""
        if not self.profile:
            return {
                'match_score': 0,
                'match_reasons': ['Profile not loaded'],
                'missing_skills': [],
                'strong_matches': [],
                'analysis': 'Profile data not available'
            }
        
        try:
            # Extract key job information
            job_info = {
                'title': job.get('title', ''),
                'department': job.get('department', ''),
                'team': job.get('team', ''),
                'description': job.get('descriptionPlain', ''),
                'requirements': job.get('requirements', ''),
                'location': job.get('location', ''),
                'employment_type': job.get('employmentType', ''),
                'is_remote': job.get('isRemote', False)
            }
            
            # Create analysis prompt
            analysis_prompt = self.create_analysis_prompt(job_info, self.profile)
            
            # Call Claude API for analysis
            response = self.call_claude_api(analysis_prompt)
            
            if response:
                return self.parse_analysis_response(response)
            else:
                # Fallback to basic keyword matching
                return self.basic_keyword_analysis(job_info, self.profile)
                
        except Exception as e:
            logger.error(f"Error analyzing job match: {e}")
            return self.basic_keyword_analysis(job_info, self.profile)
    
    def create_analysis_prompt(self, job_info: Dict, profile: Dict) -> str:
        """Create a detailed prompt for Claude to analyze job match"""
        prompt = f"""
You are an expert career advisor and recruiter. Analyze how well this candidate matches the given job posting.

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

JOB POSTING:
Title: {job_info['title']}
Department: {job_info['department']}
Team: {job_info['team']}
Location: {job_info['location']}
Employment Type: {job_info['employment_type']}
Remote: {job_info['is_remote']}

Job Description:
{job_info['description'][:2000]}  # Limit description length

Provide your analysis in the following JSON format:
{{
    "match_score": <integer from 0-100>,
    "match_reasons": [
        "<specific reason why this is a good match>",
        "<another specific matching factor>"
    ],
    "missing_skills": [
        "<skill mentioned in job that candidate lacks>",
        "<another missing requirement>"
    ],
    "strong_matches": [
        "<candidate strength that aligns with job>",
        "<another strong alignment>"
    ],
    "analysis": "<2-3 sentence summary of the overall fit>",
    "recommendation": "<should_apply|consider_applying|weak_match>",
    "salary_fit": "<assessment of candidate's experience level vs likely salary>",
    "growth_potential": "<how this role could advance candidate's career>"
}}

Consider these factors in your scoring:
- Technical skills alignment (40%)
- Experience level match (25%) 
- Industry/domain fit (15%)
- Location/remote preferences (10%)
- Career growth potential (10%)

Be honest but constructive. Focus on specific alignments and gaps.
"""
        return prompt
    
    def call_claude_api(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Call Claude API with retry logic"""
        headers = {
            "Content-Type": "application/json",
        }
        
        data = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url, 
                    headers=headers, 
                    json=data, 
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result['content'][0]['text']
                else:
                    logger.warning(f"Claude API returned status {response.status_code}: {response.text}")
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Claude API request failed (attempt {attempt + 1}): {e}")
                
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
        
        logger.error("Failed to get response from Claude API after all retries")
        return None
    
    def parse_analysis_response(self, response_text: str) -> Dict:
        """Parse Claude's JSON response"""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON object directly
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response_text
            
            analysis = json.loads(json_str)
            
            # Validate and clean the analysis
            return {
                'match_score': max(0, min(100, int(analysis.get('match_score', 0)))),
                'match_reasons': analysis.get('match_reasons', [])[:5],  # Limit to 5
                'missing_skills': analysis.get('missing_skills', [])[:5],
                'strong_matches': analysis.get('strong_matches', [])[:5],
                'analysis': analysis.get('analysis', 'Analysis not available')[:500],
                'recommendation': analysis.get('recommendation', 'consider_applying'),
                'salary_fit': analysis.get('salary_fit', 'Unknown'),
                'growth_potential': analysis.get('growth_potential', 'Unknown')
            }
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.error(f"Response was: {response_text[:500]}...")
            
            # Try to extract score from text if JSON parsing fails
            score_match = re.search(r'score[^\d]*(\d+)', response_text, re.IGNORECASE)
            score = int(score_match.group(1)) if score_match else 50
            
            return {
                'match_score': max(0, min(100, score)),
                'match_reasons': ['Analysis from Claude API'],
                'missing_skills': [],
                'strong_matches': [],
                'analysis': response_text[:300] + '...' if len(response_text) > 300 else response_text,
                'recommendation': 'consider_applying',
                'salary_fit': 'Unknown',
                'growth_potential': 'Unknown'
            }
    
    def basic_keyword_analysis(self, job_info: Dict, profile: Dict) -> Dict:
        """Fallback keyword-based matching when Claude API is unavailable"""
        try:
            # Get job text for analysis
            job_text = (
                job_info.get('title', '') + ' ' +
                job_info.get('description', '') + ' ' +
                job_info.get('department', '') + ' ' +
                job_info.get('team', '')
            ).lower()
            
            # Extract candidate skills
            all_skills = set()
            tech_skills = profile.get('technical_skills', {})
            for skill_level in tech_skills.values():
                if isinstance(skill_level, list):
                    all_skills.update([s.lower() for s in skill_level])
                elif isinstance(skill_level, dict):
                    for skills_list in skill_level.values():
                        all_skills.update([s.lower() for s in skills_list])
            
            # Add other skills
            all_skills.update([s.lower() for s in profile.get('soft_skills', [])])
            all_skills.update([s.lower() for s in profile.get('certifications', [])])
            
            # Find matches
            matched_skills = []
            for skill in all_skills:
                if skill in job_text:
                    matched_skills.append(skill)
            
            # Calculate basic score
            base_score = min(len(matched_skills) * 10, 70)  # Max 70 from skills
            
            # Bonus for title match
            candidate_titles = [t.lower() for t in profile.get('personal_info', {}).get('preferred_roles', [])]
            job_title = job_info.get('title', '').lower()
            title_bonus = 20 if any(title in job_title for title in candidate_titles) else 0
            
            # Location bonus
            location_bonus = 10 if 'san francisco' in job_info.get('location', '').lower() or job_info.get('is_remote') else 0
            
            final_score = min(base_score + title_bonus + location_bonus, 100)
            
            return {
                'match_score': final_score,
                'match_reasons': [f"Matched skills: {', '.join(matched_skills[:3])}"] if matched_skills else [],
                'missing_skills': ['Detailed analysis requires AI API'],
                'strong_matches': matched_skills[:3],
                'analysis': f"Basic keyword analysis found {len(matched_skills)} matching skills. For detailed analysis, configure Claude API access.",
                'recommendation': 'should_apply' if final_score >= 70 else 'consider_applying' if final_score >= 50 else 'weak_match',
                'salary_fit': 'Basic analysis',
                'growth_potential': 'Basic analysis'
            }
            
        except Exception as e:
            logger.error(f"Error in basic keyword analysis: {e}")
            return {
                'match_score': 50,
                'match_reasons': ['Analysis error'],
                'missing_skills': [],
                'strong_matches': [],
                'analysis': 'Analysis failed',
                'recommendation': 'consider_applying',
                'salary_fit': 'Unknown',
                'growth_potential': 'Unknown'
            }
    
    def batch_analyze_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Analyze multiple jobs and add match scores"""
        analyzed_jobs = []
        
        for i, job in enumerate(jobs):
            try:
                logger.info(f"Analyzing job {i+1}/{len(jobs)}: {job.get('title')}")
                
                match_analysis = self.analyze_job_match(job)
                
                # Add match analysis to job data
                job['match_analysis'] = match_analysis
                analyzed_jobs.append(job)
                
                # Rate limiting - wait between API calls
                if i < len(jobs) - 1:  # Don't wait after the last job
                    time.sleep(1)  # 1 second between jobs to be respectful to API
                    
            except Exception as e:
                logger.error(f"Failed to analyze job {job.get('title', 'Unknown')}: {e}")
                # Add default analysis for failed jobs
                job['match_analysis'] = {
                    'match_score': 0,
                    'match_reasons': ['Analysis failed'],
                    'missing_skills': [],
                    'strong_matches': [],
                    'analysis': 'Failed to analyze this position',
                    'recommendation': 'manual_review',
                    'salary_fit': 'Unknown',
                    'growth_potential': 'Unknown'
                }
                analyzed_jobs.append(job)
        
        logger.info(f"Completed analysis for {len(analyzed_jobs)} jobs")
        return analyzed_jobs
    
    def get_match_score_emoji(self, score: int) -> str:
        """Get emoji representation of match score"""
        if score >= 80:
            return "🎯"
        elif score >= 70:
            return "✅"
        elif score >= 60:
            return "👍"
        elif score >= 40:
            return "⚠️"
        else:
            return "❌"
    
    def get_recommendation_emoji(self, recommendation: str) -> str:
        """Get emoji for recommendation"""
        emoji_map = {
            'should_apply': '🚀',
            'consider_applying': '🤔',
            'weak_match': '⚠️',
            'manual_review': '👀'
        }
        return emoji_map.get(recommendation, '❓')
