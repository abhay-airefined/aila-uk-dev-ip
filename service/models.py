from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict
from pydantic import validator

class Party(BaseModel):
    name: str
    role: Literal["Plaintiff", "Defendant"]

class Fact(BaseModel):
    fact: str
    status: Literal["Agreed", "Disputed"]

class RelevantCase(BaseModel):
    case_name: str
    jurisdiction_code: str
    case_text: str
class SuggestedRuling(BaseModel):
    issue: str
    evidence: str
    relevant_cases: List[RelevantCase]
    suggested_ruling: str
    confidence_score: int
    confidence_score_explanation: str
    
class Issue(BaseModel):
    issue: str
    search_term: str

class Issues(BaseModel):
    issues: list[Issue]

class FilteredArticle(BaseModel):
    "Represents a single legal article relevant to the case"
    case_name: str
    jurisdiction_code: str
    case_text: str
    explanation: str
    issue_numbers: List[int]

class FilteredArticles(BaseModel):
    "Represents a list of legal articles relevant to the case"
    relevant_cases: List[FilteredArticle]
    
class JudicialAnalysis(BaseModel):
    parties: List[Party]
    facts: List[Fact]
    suggested_rulings: List[SuggestedRuling]
    
class FinalRuling(BaseModel):
    final_court_orders: List[str]
    final_ruling: str
    judgement: Literal["Plaintiff", "Defendant", "Split Judgement"]
    confidence_score: int
    
class ComplexityDetail(BaseModel):
    """Details of the case complexity"""
    rating: Literal["Low", "Medium", "High"]
    explanation: str

class CategoryDetail(BaseModel):
    """Details of the case category"""
    name: Literal[
        'Goods Not Received or Defective',
        'Services Not Rendered or Poor Quality',
        'Deposit or Refund Disputes',
        'Unpaid Loans or Money Owed',
        'Contract Disputes',
        'Property Damage',
        'Neighbour or Nuisance Disputes',
        'Employment or Work Disputes',
        'Tenancy Issues',
        'Harassment or Misconduct',
        'Other'
    ]
    explanation: str
    
class Classification(BaseModel):
    """Model for case classification response using nested models"""
    complexity: ComplexityDetail
    category: CategoryDetail
    
class CaseMemorandum(BaseModel):
    english_markdown_memorandum: str
    arabic_markdown_memorandum: str