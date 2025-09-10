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
import os

logger = logging.getLogger(__name__)

class JobMatcher:
    """AI-powered job matching using Claude API"""
    
    def __init__(self, profile_path: str = "profile.json", api_key: Optional[str] = None):
        """Initialize with candidate profile and API configuration"""
        self.profile_path = Path(profile_path)
        self.profile = self.load_profile()
        self.api_url = "https://api.anthropic.com/v1/messages"
        
        # Get API key from parameter, environment variable, or config
        self.api_key = (
            api_key or 
            os.environ.get('ANTHROPIC_API_KEY') or 
            os.environ.get('CLAUDE_API_KEY')
        )
        
        if self.api_key:
            logger.info("Claude API key configured - AI matching enabled")
        else:
            logger.warning("No Claude API key found - falling back to keyword matching only")
        
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
                'analysis': 'Profile data not available',
                'recommendation': 'manual_review',
                'salary_fit': 'Unknown',
                'growth_potential': 'Unknown'
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
            
            # Try AI analysis first if API key is available
            if self.api_key:
                analysis_prompt = self.create_analysis_prompt(job_info, self.profile)
                response = self.call_claude_api(analysis_prompt)
                
                if response:
                    return self.parse_analysis_response(response)
                else:
                    logger.warning("Claude API failed, falling back to keyword analysis")
            
            # Fallback to keyword analysis
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

Respond ONLY with valid JSON. Do not include any text outside the JSON structure.
"""
        return prompt
    
    def call_claude_api(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Call Claude API with retry logic"""
        if not self.api_key:
            logger.warning("No API key available for Claude API")
            return None
            
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        data = {
            "model": "claude-3-5-sonnet-20241022",
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
                elif response.status_code == 401:
                    logger.error("Claude API authentication failed - check your API key")
                    return None
                elif response.status_code == 429:
                    logger.warning(f"Claude API rate limit hit, retrying in {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)
                    continue
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
            base_score = min(len(matched_skills) * 8, 60)  # Max 60 from skills
            
            # Bonus for title match
            candidate_titles = [t.lower() for t in profile.get('personal_info', {}).get('preferred_roles', [])]
            job_title = job_info.get('title', '').lower()
            title_bonus = 25 if any(title in job_title for title in candidate_titles) else 0
            
            # Location bonus
            location_bonus = 15 if 'san francisco' in job_info.get('location', '').lower() or job_info.get('is_remote') else 0
            
            final_score = min(base_score + title_bonus + location_bonus, 100)
            
            # Generate meaningful analysis
            analysis_parts = []
            if skill_details:
                expert_skills = [s for s, level in skill_details if level == 'expert']
                if expert_skills:
                    analysis_parts.append(f"Strong match on expert skills: {', '.join(expert_skills[:3])}")
            
            if title_score >= 20:
                analysis_parts.append("Excellent job title alignment")
            elif title_score >= 10:
                analysis_parts.append("Good job title match")
                
            if exp_score >= 12:
                analysis_parts.append("Experience level is well-suited")
                
            analysis_text = '. '.join(analysis_parts) if analysis_parts else "Basic skills analysis completed"
            
            # Identify missing skills (simple heuristic)
            job_keywords = ['python', 'javascript', 'react', 'aws', 'kubernetes', 'machine learning', 'sql']
            found_skills = [s.lower() for s, _ in skill_details]
            potential_missing = [kw for kw in job_keywords if kw in job_text and kw not in found_skills]
            
            return {
                'match_score': final_score,
                'match_reasons': [
                    f"Found {len(skill_details)} relevant skills" if skill_details else "Basic compatibility analysis",
                    f"Job title alignment: {title_score}/25 points" if title_score > 0 else None,
                    f"Experience level fit: {exp_score}/15 points" if exp_score > 0 else None,
                    f"Location preference: {location_score}/10 points" if location_score > 0 else None
                ],
                'missing_skills': potential_missing[:3],
                'strong_matches': [f"{skill} ({level})" for skill, level in skill_details[:4]],
                'analysis': f"{analysis_text}. Score: {final_score}/100. Enhanced keyword analysis with skill weighting.",
                'recommendation': recommendation,
                'salary_fit': f'Experience level ({experience_years} years) suggests {"senior" if experience_years >= 5 else "mid" if experience_years >= 3 else "junior"} role fit',
                'growth_potential': 'Enhanced analysis - configure Claude API for detailed career growth assessment'
            }
            
        except Exception as e:
            logger.error(f"Error in basic keyword analysis: {e}")
            return {
                'match_score': 50,
                'match_reasons': ['Analysis error'],
                'missing_skills': [],
                'strong_matches': [],
                'analysis': 'Analysis failed',
                'recommendation': 'manual_review',
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
                if i < len(jobs) - 1 and self.api_key:  # Only wait if using API
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

    @staticmethod
    def setup_instructions():
        """Print setup instructions for Claude API"""
        print("""
🔧 CLAUDE API SETUP INSTRUCTIONS:

1. Get your API key from: https://console.anthropic.com/
2. Add it to your environment in one of these ways:

   For GitHub Actions (recommended):
   - Go to your repo Settings > Secrets and variables > Actions
   - Add new secret: ANTHROPIC_API_KEY = your-api-key-here
   
   For local development:
   - export ANTHROPIC_API_KEY="your-api-key-here"
   - Or add to your .env file
   
   For Netlify deployment:
   - Go to Site settings > Environment variables
   - Add: ANTHROPIC_API_KEY = your-api-key-here

3. The system will automatically detect and use the API key
4. Without an API key, it falls back to basic keyword matching

💰 API COSTS:
- Claude 3.5 Sonnet: ~$3 per 1M input tokens, ~$15 per 1M output tokens
- Typical job analysis: ~500-1000 tokens per job
- Daily cost for 5-10 new jobs: ~$0.01-0.05

🔒 SECURITY:
- Never commit API keys to your repository
- Use environment variables or GitHub Secrets
- The job matcher will warn if no API key is found
        """)
