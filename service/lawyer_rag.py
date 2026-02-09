import os
from openai import AzureOpenAI
import logging
from typing import List, Optional, Literal
import datetime
import random
import json
from io import BytesIO
from pydantic import BaseModel
from functools import wraps
import time
# from .. import count_tokens
from service.lawyer_prompt import lawyer_query_system_prompt, lawyer_query_prompt, lawyer_filter_system_prompt, lawyer_filter_human_prompt, lawyer_decision_system_prompt, lawyer_judge_prompt, lawyer_final_ruling_system_prompt, lawyer_final_ruling_human_prompt, lawyer_classification_system_prompt, lawyer_classification_prompt
from service.rag_utils import find_relevant_chunks, get_llm_response
from service.models import JudicialAnalysis, Issues, FilteredArticles, FinalRuling
from service.format_utils import format_relevant_cases

def retry_operation(max_attempts=3, delay_seconds=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts == max_attempts:
                        logging.error(f"Failed after {max_attempts} attempts. Error: {str(e)}")
                        raise
                    logging.warning(f"Attempt {attempts} failed. Retrying in {delay_seconds} seconds. Error: {str(e)}")
                    time.sleep(delay_seconds)
            return None
        return wrapper
    return decorator

@retry_operation()
def get_llm_response_with_retry(*args, **kwargs):
    return get_llm_response(*args, **kwargs)

@retry_operation()
def update_case_status(table_client, case_id: str, current_step: str, completed_step: str = None, result: dict = None):
    """Update the case status in the table storage"""
    case_entity = table_client.get_entity('cases', case_id)
    
    # Update current step
    case_entity['CurrentStep'] = current_step
    
    # Add completed step if provided
    if completed_step:
        completed_steps = json.loads(case_entity['CompletedSteps'])
        completed_steps.append(completed_step)
        case_entity['CompletedSteps'] = json.dumps(completed_steps)
    
    # Update result if provided
    if result:
        case_entity['Result'] = json.dumps(result)
        case_entity['Status'] = 'completed'
    
    table_client.update_entity(case_entity)

@retry_operation()
def get_case_entity(table_client, case_id: str):
    return table_client.get_entity('cases', case_id)

@retry_operation()
def search_with_retry(search_term: str, n_results: int = 5):
    return find_relevant_chunks(search_term, n_results=n_results)

def run_lawyer_rag(plaintiff_case_text: str, defendant_case_text: str, case_id: str, table_client) -> dict:
    try:
        # Get case entity to retrieve case number
        case_entity = get_case_entity(table_client, case_id)
        case_number = case_entity.get('CaseNumber')
        
        update_case_status(table_client, case_id, 'Analysing case documents')
        time.sleep(1)
        
        update_case_status(
            table_client, 
            case_id, 
            'Identifying case matters',
            'Analysing case documents'
        )
        
        # Agent 2
        issues_result = get_llm_response_with_retry(
            system_prompt=lawyer_query_system_prompt(),
            human_prompt=lawyer_query_prompt(plaintiff_case_text, defendant_case_text),
            response_format=Issues
        )

        issues = [issue.issue for issue in issues_result.issues]
        issues_formatted = "\n".join([f"Issue {i+1}: {issue}" for i, issue in enumerate(issues)])
        logging.info(f"[API INFO] Identified {len(issues)} issues:\n{issues_formatted}")

        update_case_status(
            table_client, 
            case_id, 
            'Retrieving relevant cases',
            'Identifying case matters'
        )
        logging.info(f"[API INFO] Retrieved relevant cases")
        
        # Agent 3
        query_results = []
        for issue in issues_result.issues:
            search_results = search_with_retry(issue.search_term, n_results=2)
            # search_results_metadata = [{"id": r["id"], **r["metadata"]} for r in search_results]
            query_results.append({"query": issue.search_term, "description": issue.issue, "results": search_results})
            
        relevant_cases_formatted = format_relevant_cases(query_results)
        logging.info(f"[API INFO] Formatted relevant cases")

        update_case_status(
            table_client, 
            case_id, 
            'Filtering relevant cases',
            'Retrieving relevant cases'
        )
        logging.info(f"[API INFO] Filtered relevant cases")
        
        # Agent 4
        filtered_articles = get_llm_response_with_retry(
            system_prompt=lawyer_filter_system_prompt(),
            human_prompt=lawyer_filter_human_prompt(plaintiff_case_text, defendant_case_text, relevant_cases_formatted),
            response_format=FilteredArticles
        )

        # filtered_articles_formatted = format_filtered_articles(filtered_articles)
        logging.info(f"[API INFO] Formatted filtered articles")

        update_case_status(
            table_client, 
            case_id, 
            'Analysing case',
            'Filtering relevant cases'
        )
        
        # Agent 5
        analysis = get_llm_response_with_retry(
            system_prompt=lawyer_decision_system_prompt(),
            human_prompt=lawyer_judge_prompt(plaintiff_case_text, defendant_case_text, issues_formatted, filtered_articles),
            response_format=JudicialAnalysis
        )
        
        logging.info(f"[API INFO] Analysed case")

        # analysis = enrich_analysis_with_article_text(analysis)

        # Step 6: Draft final court orders
        update_case_status(
            table_client, 
            case_id, 
            'Drafting final court orders',
            'Analysing case'
        )
        
        final_ruling = get_llm_response_with_retry(
            system_prompt=lawyer_final_ruling_system_prompt(),
            human_prompt=lawyer_final_ruling_human_prompt(analysis),
            response_format=FinalRuling
        )
        
        logging.info(f"[API INFO] Drafted final court orders")
        
        final_analysis = analysis.model_dump()
        final_analysis["final_court_orders"] = final_ruling.final_court_orders
        final_analysis["final_ruling"] = final_ruling.final_ruling
        final_analysis["judgement"] = final_ruling.judgement
        final_analysis["confidence_score"] = final_ruling.confidence_score
        final_analysis["case_number"] = case_number

        # Update final status with result
        update_case_status(
            table_client, 
            case_id, 
            'Complete',
            'Drafting final court orders',
            final_analysis
        )
        
        return final_analysis
        
    except Exception as e:
        logging.error(f"Error in run_rag: {str(e)}")
        # Update case status to error
        case_entity = table_client.get_entity('cases', case_id)
        case_entity['Status'] = 'error'
        case_entity['Error'] = str(e)
        table_client.update_entity(case_entity)
        raise e