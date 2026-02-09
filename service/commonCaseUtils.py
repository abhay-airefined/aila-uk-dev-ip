# from models import JudicialAnalysis
# from rag_utils import fetch_article_text
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

def format_relevant_articles(query_results: List[dict]) -> str:
    relevant_articles_formatted = ""

    for query_number, query_result in enumerate(query_results, start=1):
        # relevant_articles_formatted += f"Query {query_number}: \"{query_result['query']}\"\n"
        relevant_articles_formatted += f"Issue {query_number}: \"{query_result['description']}\"\nRetrieved Articles:\n"
        for result_number, result in enumerate(query_result["results"], start=1):
            # relevant_articles_formatted += f"\tResult Number: {result_number}\n"
            relevant_articles_formatted += f"\tArticle Number: {result['article_number']}\n"
            relevant_articles_formatted += f"\tArticle ID: {result['id']}\n"
            relevant_articles_formatted += f"\tLegislation Title: {result['legislation_title']}\n"
            relevant_articles_formatted += f"\tLegislation ID: {result['legislation_id']}\n"
            relevant_articles_formatted += f"\tArticle Text: {result['article_text']}\n\n"
            
        relevant_articles_formatted += "\n\n"

    return relevant_articles_formatted

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

# def format_judicial_analysis(analysis: JudicialAnalysis):
#     output = []

#     # Parties
#     output.append("PARTIES:")
#     for party in analysis.parties:
#         output.append(f"  • {party.name} ({party.role})")

#     # Facts
#     output.append("\nFACTS:")
#     for i, fact in enumerate(analysis.facts, 1):
#         output.append(f"  {i}. [{fact.status}] {fact.fact}")

#     # Suggested Rulings
#     output.append("\nSUGGESTED RULINGS:")
#     for i, ruling in enumerate(analysis.suggested_rulings, 1):
#         output.append(f"\nISSUE {i}: {ruling.issue}")
#         output.append(f"Evidence:")
#         output.append(f"  {ruling.evidence}")
        
#         if ruling.relevant_articles:
#             output.append("Relevant Articles:")
#             for article in ruling.relevant_articles:
#                 output.append(f"  • Article {article.article_number} (ID: {article.article_id})")
#                 output.append(f"    {article.legislation_title}")
#                 output.append(f"    (ID: {article.legislation_id})")
#                 output.append(f"    Article Quote: {article.article_quote}")
#                 output.append(f"    Explanation: {article.explanation}")
#                 try:
#                     full_article_text = article.full_article_text.replace('\n', '\n\t\t')
#                 except Exception as e:
#                     full_article_text = ""
#                 output.append(f"    Full Article Text: {full_article_text}")

#         output.append("Suggested Ruling:")
#         output.append(f"  {ruling.suggested_ruling}")
        
#     return "\n".join(output)


def get_next_case_number(table_client, firm_short_name: str) -> str:
    """
    Get the next sequential case number for a specific law firm.
    The case number format is {firm_short_name}-{year}-{sequence}
    where sequence is a 5-digit number that resets each year.
    The case number is used as the RowKey in the table.
    
    Args:
        table_client: Azure Table client for ailalawyercases
        firm_short_name: Short name of the law firm (e.g., SMITH)
        
    Returns:
        str: Next case number in the format FIRM-YYYY-XXXXX
    """
    try:
        current_year = datetime.now().year
        
        # Query cases for this firm
        # PartitionKey is the firm_short_name
        query = f"PartitionKey eq '{firm_short_name}'"
        entities = list(table_client.query_entities(query))
        
        # Filter for current year's cases using RowKey
        # Since case number is now the RowKey, we can use it directly
        current_year_cases = [
            entity for entity in entities 
            if entity['RowKey'].startswith(f"{firm_short_name}-{current_year}")
        ]
        
        if not current_year_cases:
            # First case for this firm this year
            return f"{firm_short_name}-{current_year}-00001"
            
        # Extract sequence numbers from RowKey and find the highest
        sequence_numbers = []
        for case in current_year_cases:
            try:
                seq_num = int(case['RowKey'].split('-')[-1])
                sequence_numbers.append(seq_num)
            except (ValueError, IndexError):
                continue
        
        if not sequence_numbers:
            # No valid sequence numbers found
            return f"{firm_short_name}-{current_year}-00001"
            
        # Get next sequence number
        next_seq = max(sequence_numbers) + 1
        return f"{firm_short_name}-{current_year}-{str(next_seq).zfill(5)}"
            
    except Exception as e:
        logging.error(f"Error getting next case number: {str(e)}")
        # In case of any error, return a safe fallback
        return f"{firm_short_name}-{current_year}-00001"