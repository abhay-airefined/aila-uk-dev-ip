from service.models import JudicialAnalysis, FilteredArticles
# from ..service.rag_utils import RAGUtils
from typing import List
import logging
from datetime import datetime

def format_timestamp(timestamp_str):
    """Format timestamp into date and time strings for frontend display"""
    dt = datetime.fromisoformat(timestamp_str)
    
    # Format date as "DD Month YYYY"
    # Using %d instead of %-d for cross-platform compatibility
    date_str = dt.strftime("%d %B %Y").lstrip("0")
    
    # Format time as "H:MM am/pm"
    # Using %I instead of %-I for cross-platform compatibility
    hour = dt.strftime("%I").lstrip("0")
    time_str = f"{hour}:{dt.strftime('%M%p')}".lower()
    
    return {
        "date": date_str,
        "time": time_str
    }

def format_relevant_cases(query_results: List[dict]) -> str:
    relevant_cases_formatted = ""

    for query_number, query_result in enumerate(query_results, start=1):
        # relevant_articles_formatted += f"Query {query_number}: \"{query_result['query']}\"\n"
        relevant_cases_formatted += f"Issue {query_number}: \"{query_result['description']}\"\nRetrieved Cases:\n"
        for result_number, result in enumerate(query_result["results"], start=1):
            # relevant_articles_formatted += f"\tResult Number: {result_number}\n"
            relevant_cases_formatted += f"\tCase Name: {result['caseName']}\n"
            relevant_cases_formatted += f"\tJurisdiction Code: {result['jurisdictionCode']}\n"
            # relevant_articles_formatted += f"\tPublished Date: {result['publishedDate']}\n"
            relevant_cases_formatted += f"\tRaw Text: {result['rawText']}\n"
            # relevant_articles_formatted += f"\: {result['rawText']}\n"
            # relevant_articles_formatted += f"\tArticle Text: {result['article_text']}\n\n"
            
        relevant_cases_formatted += "\n\n"

    return relevant_cases_formatted

# def format_filtered_articles(filtered_articles: FilteredArticles) -> str:
#     filtered_articles_formatted = ""

#     for article in filtered_articles.relevant_articles:
#         try:
#             article_text = fetch_article_text(article.article_id)
#         except Exception as e:
#             logging.error(f"[API ERROR][format_filtered_articles] Failed to fetch article {article.article_id}: {str(e)}")
#             article_text = "Article text not available"
            
#         filtered_articles_formatted += f"Article Number: {article.article_number}\n"
#         filtered_articles_formatted += f"Article ID: {article.article_id}\n"
#         filtered_articles_formatted += f"Legislation Title: {article.legislation_title}\n"
#         filtered_articles_formatted += f"Legislation ID: {article.legislation_id}\n"
#         filtered_articles_formatted += f"Article Text: {article_text}\n"
#         filtered_articles_formatted += f"Explanation: {article.explanation}\n\n"
#         filtered_articles_formatted += "\n"

#     return filtered_articles_formatted


# def enrich_analysis_with_article_text(analysis: JudicialAnalysis) -> JudicialAnalysis:
#     """
#     Enriches a JudicialAnalysis by fetching and adding the full article text
#     for each RelevantArticle in the suggested rulings.
#     """
#     for ruling in analysis.suggested_rulings:
#         for article in ruling.relevant_articles:
#             try:
#                 article.full_article_text = fetch_article_text(article.article_id)
#             except Exception as e:
#                 logging.error(f"[API ERROR][enrich_analysis_with_article_text] Failed to fetch article {article.article_id}: {str(e)}")
#                 article.full_article_text = None
#     return analysis

def format_judicial_analysis(analysis: JudicialAnalysis):
    output = []

    # Parties
    output.append("PARTIES:")
    for party in analysis.parties:
        output.append(f"  • {party.name} ({party.role})")

    # Facts
    output.append("\nFACTS:")
    for i, fact in enumerate(analysis.facts, 1):
        output.append(f"  {i}. [{fact.status}] {fact.fact}")

    # Suggested Rulings
    output.append("\nSUGGESTED RULINGS:")
    for i, ruling in enumerate(analysis.suggested_rulings, 1):
        output.append(f"\nISSUE {i}: {ruling.issue}")
        output.append(f"Evidence:")
        output.append(f"  {ruling.evidence}")
        
        if ruling.relevant_cases:
            output.append("Relevant Cases:")
            for case in ruling.relevant_cases:
                output.append(f"  • Case {case.case_name} (ID: {case.jurisdiction_code})")
                output.append(f"    {case.case_text}")
                # output.append(f"    Explanation: {case.explanation}")

        output.append("Suggested Ruling:")
        output.append(f"  {ruling.suggested_ruling}")
        
    return "\n".join(output)


def get_next_case_number(table_client) -> str:
    """Get the next sequential case number"""
    try:
        # Query all cases and sort by StartTime descending
        query = "PartitionKey eq 'cases'"
        entities = list(table_client.query_entities(query))
        
        # Filter out entities with null case numbers and sort by StartTime descending
        valid_entities = [e for e in entities if 'CaseNumber' in e and e['CaseNumber'] is not None]
        sorted_entities = sorted(valid_entities, key=lambda x: x['StartTime'], reverse=True)
        
        current_year = datetime.now().year
        
        if not sorted_entities:
            # First case of the year or no valid case numbers
            return f"DXB/{current_year}/00001"
            
        # Get the latest case number
        latest_case = sorted_entities[0]
        latest_number = latest_case['CaseNumber']
        
        # Extract the sequential number from the latest case
        try:
            latest_seq = int(latest_number.split('/')[-1])
            next_seq = str(latest_seq + 1).zfill(5)
            return f"DXB/{current_year}/{next_seq}"
        except (ValueError, IndexError):
            # If there's any error parsing the number, start from 1
            return f"DXB/{current_year}/00001"
            
    except Exception as e:
        logging.error(f"Error getting next case number: {str(e)}")
        # Fallback to starting from 1
        return f"DXB/{datetime.now().year}/00001"