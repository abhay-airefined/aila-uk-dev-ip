import os
import json
import logging
import re
from typing import List, Dict
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

class PolicyBenefitParser:
    def __init__(self, markdown_text: str, document_url: str, filename: str, org_id: int, md5_hash: str):
        self.document_url = document_url
        self.filename = filename
        self.org_id = org_id
        self.md5_hash = md5_hash

        # Extract footnotes from the original text before any cleaning
        self.footnotes = self._extract_footnotes(markdown_text)
        
        # Preprocess the text to remove headers, footers, and the footnote block itself
        self.text = self._preprocess_text(markdown_text)

        # Azure OpenAI Chat configuration
        self.openai_api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
        self.openai_api_base=os.getenv("AZURE_OPENAI_ENDPOINT")
        self.openai_api_version=os.getenv("AZURE_OPENAI_EMBEDDING_VERSION")
        self.deployment_name=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")

        self.chat_client = AzureOpenAI(
            api_key=self.openai_api_key,
            azure_endpoint=self.openai_api_base,
            api_version=self.openai_api_version
        )

    def _preprocess_text(self, text: str) -> str:
        """
        Cleans the raw text from the PDF conversion by removing recurring headers,
        footers, and the final footnote block, which is handled separately.
        """
        # Remove the recurring page headers and schedule of benefits titles
        text = re.sub(r"National Health Insurance Company – Daman.*Page No\(s\).:.*\n?", "", text)
        text = re.sub(r"\nSchedule of Benefits.*?\n", "\n", text)
        
        # Remove the final reference line
        text = re.sub(r"\nSOB REF NO:.*", "", text)

        # Find the start of the footnote section (e.g., starts with '1 Please note:') and truncate the text there
        footnote_start_match = re.search(r"\n\s*1\s+Please note:", text)
        if footnote_start_match:
            text = text[:footnote_start_match.start()]
        
        # Normalize whitespace and remove excessive blank lines
        lines = [line.strip() for line in text.split('\n')]
        non_empty_lines = [line for line in lines if line]
        
        return "\n".join(non_empty_lines)

    def _extract_footnotes(self, text: str) -> Dict[int, str]:
        """Extracts footnotes from the raw text."""
        footnote_matches = re.findall(r"\n(\d{1,2})\s+(.*?)(?=\n\d{1,2}\s|\Z)", text, re.DOTALL)
        return {
            int(num): note.strip().replace('\n', ' ')
            for num, note in footnote_matches
        }

    def _build_llm_prompt(self) -> str:
        # The user's sample JSON structure
        json_format = {
          "section": "Section Name (e.g. 'Inpatient Treatment' for benefits, 'Plan Information' for general plan details)",
          "title": "Title (e.g. 'Inpatient & Day Treatment' for benefits, 'Annual Benefit Limit' for plan details)",
          "description": "Description text (e.g. coverage limits, conditions, amounts)",
          "notes": "['Any footnote or additional notes such as authorization or claim conditions']",
          "coverage_network": "Coverage detail for in-network (e.g. '100% covered') - leave empty for plan information",
          "coverage_nonNetwork": "Coverage detail for out-of-network (e.g. '80% covered') - leave empty for plan information",
          "rawText": "Exact raw input provided",
        }

        example_input_plan = """
        Plan Name: Care Gold DNE with Dental- Individual
        Annual Benefit Limit: AED 2,500,000 Per Person Per Policy Year
        """

        example_output_plan = {
          "section": "Plan Information",
          "title": "Annual Benefit Limit",
          "description": "AED 2,500,000 Per Person Per Policy Year",
          "notes": [],
          "coverage_network": "",
          "coverage_nonNetwork": "",
          "rawText": "Benefits section:Plan Information, benefit:Annual Benefit Limit AED 2,500,000 Per Person Per Policy Year"
        }

        example_input_benefit = """
        INPATIENT & DAY-CARE TREATMENT1,2
        (Including Pre & Post-Hospitalization Treatment Covered)
        In-Network: 100% covered
        Out-of-Network: 80% covered
        """

        example_output_benefit = {
          "section": "INPATIENT & DAY-CARE TREATMENT",
          "title": "INPATIENT & DAY-CARE TREATMENT1,2",
          "description": "(Including Pre & Post-Hospitalization Treatment Covered)",
          "notes": [
            "Pre-authorization is required for all inpatient treatments.",
            "Subject to co-payment."
          ],
          "coverage_network": "100% covered",
          "coverage_nonNetwork": "80% covered",
          "rawText": "INPATIENT & DAY-CARE TREATMENT1,2 (Including Pre & Post-Hospitalization Treatment Covered) In-Network: 100% covered Out-of-Network: 80% covered"
        }

        prompt = f"""
        You are an expert at parsing insurance policy documents into structured JSON.
        Your task is to extract ALL information from the provided markdown text and format them into a list of JSON objects.
        
        **CRITICAL: DO NOT MISS ANY INFORMATION. Capture everything completely.**
        **CRITICAL: EACH BENEFIT MUST BE A SEPARATE JSON OBJECT. NEVER combine multiple benefits into one object.**
        
        **STRICT BOUNDARY RULES:**
        1. **EACH DISTINCT BENEFIT/SERVICE/COVERAGE ITEM MUST BE ITS OWN SEPARATE JSON OBJECT**
        2. **NEVER put information about other benefits in the 'notes' field of a different benefit**
        3. **The 'notes' field is ONLY for footnotes corresponding to superscript numbers in that specific benefit**
        4. **If you see multiple benefits listed, create separate JSON objects for each one**
        5. **Stop processing a benefit when you encounter the next benefit's title or section**
        
        **Instructions:**
        1.  **FIRST, extract general plan information from the top of the document including:**
            - Plan Name (e.g., "Care Gold DNE with Dental- Individual")
            - Annual Benefit Limit (e.g., "AED 2,500,000 Per Person Per Policy Year")
            - Territorial Limit information (capture the full description)
            - Network information - **IMPORTANT: Group all network information together, including:**
              * The main network description with billing details
              * Network Within UAE details
              * Network Outside UAE details
              * Any website references or additional instructions
            - Pre-existing conditions coverage
            - Any other general plan details
        2.  **THEN, analyze the text to identify distinct benefit blocks from the benefits table.**
        3.  **For plan information, group related items together instead of splitting them:**
           - Network information should be ONE entry that includes all network details
           - Don't create separate entries for "Network Within UAE" and "Network Outside UAE"
           - Include complete descriptions, not just brief summaries
        4.  **IMPORTANT: Correctly identify section boundaries and benefit hierarchies:**
           - Look for section headers that introduce a group of benefits (e.g., "Other Services covered", "Dental Module 1")
           - Individual benefits listed under section headers should use that section name
           - Items that stand alone (like "Optical not covered") should get their own section
           - Pay attention to indentation, formatting, and logical grouping
           - If multiple items are listed under a section header without their own coverage details, they belong to that section
           - Section headers often have descriptive text like "covered", "Through Service Providers Only", etc.
        5.  **CRITICAL BENEFIT SEPARATION RULES:**
           - Each line that describes a distinct service, treatment, or coverage item must be its own JSON object
           - Look for patterns like "Service Name" followed by coverage percentages
           - Look for bullet points or numbered lists - each item is typically a separate benefit
           - When you see phrases like "Annual X Screening", "Y Treatment", "Z Services" - these are separate benefits
           - Section changes (like "Maternity", "Dental", "Optical") indicate new benefit groups
        6.  For each piece of information (both general plan details and specific benefits), extract according to the JSON format provided.
        7.  **PRESERVE ALL SUPERSCRIPTS EXACTLY AS THEY APPEAR:**
           - Keep superscripts in section names exactly as written in the original text
           - Keep superscripts in titles exactly as written  
           - Keep superscripts in descriptions and detailed content exactly as written
           - Don't remove or modify any superscript numbers anywhere
        8.  **CRITICAL: For footnotes, look for superscript numbers EVERYWHERE in the text:**
             - Look in section names, titles, descriptions, and ALL detailed content
             - Look for superscript numbers like ¹, ², ³ or 1, 2, 3 directly attached to words (e.g., "Treatment¹", "Service¹,²", "tests11")
             - **Pay special attention to nested content and detailed descriptions where superscripts often appear**
             - **IMPORTANT: Section-level citations apply to ALL benefits in that section**
               * If a section name has superscripts (e.g., "Maternity 13"), include that footnote in ALL benefits under that section
               * Combine section-level footnotes with individual benefit footnotes
             - Do NOT include footnotes if there are no superscript numbers
             - If you see numbers like "16 years", "500 per day", "50%", "180 days" - these are NOT superscripts
             - Only include footnotes that correspond to the actual superscript numbers you find
        9.  When you find superscript numbers, look them up in the FOOTNOTES section below and include the corresponding text in the `notes` array.
        10. If a benefit has multiple superscripts (like `...¹,²` or content has multiple like "tests11" and "Treatment2"), include all corresponding footnote texts in the `notes` array.
        11. **For each benefit, include BOTH section-level and individual-level footnotes in the notes array.**
        12. **STRICT NOTES FIELD RULE: Leave the `notes` array empty if there are no superscript numbers anywhere in the section name, title, or description. NEVER put other benefit information in notes.**
        13. For general plan information that doesn't have network/non-network coverage, leave coverage fields empty.
        14. **ENSURE COMPLETENESS**: Read through the entire document carefully and make sure no information is missed.
        15. **BOUNDARY DETECTION**: When processing benefits, stop at clear boundaries:
            - New section headers (e.g., "Maternity", "Dental", "Optical")
            - New benefit titles that start a new line
            - Coverage percentage pairs (Network/Non-network) typically end one benefit
        16. The final output MUST be a single JSON object with a key "benefits" that contains a list of ALL extracted information (both general plan details and specific benefits). Do not return anything else.

        **JSON Format to use for each benefit:**
        ```json
        {json.dumps(json_format, indent=2)}
        ```

        **FOOTNOTES library to use for lookups:**
        ```json
        {json.dumps(self.footnotes, indent=2)}
        ```

        **Examples of how to process different types of information:**

        *Example 1 - Plan Information:*
        ```
        {example_input_plan.strip()}
        ```

        *Resulting JSON Object for plan information:*
        ```json
        {json.dumps(example_output_plan, indent=2)}
        ```

        *Example 2 - Complete Network Information (DO THIS):*
        ```
        Network (Allowing direct billing at designated provider.)
        Network Within UAE: ROYAL
        Network Outside UAE: WW exc. US CAN
        ```

        *Resulting JSON Object for complete network information:*
        ```json
        {{
          "section": "Plan Information",
          "title": "Network Information",
          "description": "Allowing direct billing at designated provider. Network Within UAE: ROYAL. Network Outside UAE: WW exc. US CAN",
          "notes": [],
          "coverage_network": "",
          "coverage_nonNetwork": "",
          "rawText": "Benefits section:Plan Information, benefit:Network Information Allowing direct billing at designated provider. Network Within UAE: ROYAL. Network Outside UAE: WW exc. US CAN"
        }}
        ```

        *Example 3 - Benefit Information:*
        ```
        {example_input_benefit.strip()}
        ```

        *Resulting JSON Object for benefit information:*
        ```json
        {json.dumps(example_output_benefit, indent=2)}
        ```

        *Example 4 - CORRECT Benefit Separation (CRITICAL - DO THIS):*
        ```
        Healthcare services for work illnesses and injuries as per Federal Law No. 8 of 1980  100% covered  80% covered
        Annual Breast Cancer Screening (applicable for females> 35 years) 2,6 100% covered  80% covered
        Annual Prostate Cancer Screening (applicable for males> 45 years) 2,7 100% covered  80% covered
        ```

        *Resulting JSON Objects (SEPARATE objects for each benefit):*
        ```json
        [
          {{
            "section": "Other Benefits",
            "title": "Healthcare services for work illnesses and injuries as per Federal Law No. 8 of 1980",
            "description": "",
            "notes": [],
            "coverage_network": "100% covered",
            "coverage_nonNetwork": "80% covered",
            "rawText": "Benefit section:Other Benefits, benefit:Healthcare services for work illnesses and injuries as per Federal Law No. 8 of 1980 Coverage: Network 100% covered Non-Network 80% covered"
          }},
          {{
            "section": "Other Benefits",
            "title": "Annual Breast Cancer Screening",
            "description": "(applicable for females> 35 years)",
            "notes": [
              "Footnote text for superscript 2",
              "Footnote text for superscript 6"
            ],
            "coverage_network": "100% covered",
            "coverage_nonNetwork": "80% covered",
            "rawText": "Benefit section:Other Benefits, benefit:Annual Breast Cancer Screening (applicable for females> 35 years) Coverage: Network 100% covered Non-Network 80% covered"
          }},
          {{
            "section": "Other Benefits",
            "title": "Annual Prostate Cancer Screening",
            "description": "(applicable for males> 45 years)",
            "notes": [
              "Footnote text for superscript 2",
              "Footnote text for superscript 7"
            ],
            "coverage_network": "100% covered",
            "coverage_nonNetwork": "80% covered",
            "rawText": "Benefit section:Other Benefits, benefit:Annual Prostate Cancer Screening (applicable for males> 45 years) Coverage: Network 100% covered Non-Network 80% covered"
          }}
        ]
        ```

        *Example 5 - Complex Section with Multiple Superscripts (DO THIS):*
        ```
        Section Name¹³ (Additional Description)
        Benefit Title²
        Including: 
        a) Detailed item: Description (content with superscript¹¹)
        b) Another item
        c) Third item
        Network: 100% covered Non-network: 80% covered
        ```

        *Resulting JSON Object (showing correct superscript preservation and footnote extraction):*
        ```json
        {{
          "section": "Section Name¹³ (Additional Description)",
          "title": "Benefit Title²", 
          "description": "Including: a) Detailed item: Description (content with superscript¹¹) b) Another item c) Third item",
          "notes": [
            "Footnote text for superscript 2",
            "Footnote text for superscript 11",
            "Footnote text for superscript 13"
          ],
          "coverage_network": "100% covered",
          "coverage_nonNetwork": "80% covered",
          "rawText": "Benefits section:Section Name¹³ (Additional Description), benefit:Benefit Title² Including: a) Detailed item: Description (content with superscript¹¹) b) Another item c) Third item Coverage: Network 100% covered Non-Network 80% covered"
        }}
        ```

        *Example 6 - Section-Level Citations Apply to All Benefits (CRITICAL):*
        ```
        Maternity 13 (Covered for Married Female only)
        Inpatient Maternity2
        Outpatient Maternity - Physician Consultation
        Maximum annual limit per person per policy year
        ```

        *Resulting JSON Objects (ALL should include footnote 13 from section name):*
        ```json
        [
          {{
            "section": "Maternity 13 (Covered for Married Female only)",
            "title": "Inpatient Maternity2",
            "description": "",
            "notes": [
              "Footnote text for superscript 2",
              "Footnote text for superscript 13"
            ]
          }},
          {{
            "section": "Maternity 13 (Covered for Married Female only)",
            "title": "Outpatient Maternity - Physician Consultation", 
            "description": "",
            "notes": [
              "Footnote text for superscript 13"
            ]
          }},
          {{
            "section": "Maternity 13 (Covered for Married Female only)",
            "title": "Maximum annual limit per person per policy year",
            "description": "",
            "notes": [
              "Footnote text for superscript 13"
            ]
          }}
        ]
        ```

        *Example 7 - Correct Table Section Handling (DO THIS):*
        ```
        Dental Module 1               Network    Non-network
        Dental²,⁴                     80% covered   80% covered
        Accidental dental treatment   100% covered  100% covered
        Optical not covered
        Other Services covered (Through Service Providers Only)
        Teleconsultation healthcare services
        Second Medical Opinion through service provider only
        ```

        *Resulting JSON Objects (showing correct section separation):*
        ```json
        [
          {{
            "section": "Dental Module 1",
            "title": "Dental²,⁴",
            "description": "",
            "notes": ["Footnote for 2", "Footnote for 4"],
            "coverage_network": "80% covered",
            "coverage_nonNetwork": "80% covered"
          }},
          {{
            "section": "Dental Module 1", 
            "title": "Accidental dental treatment",
            "description": "",
            "notes": [],
            "coverage_network": "100% covered",
            "coverage_nonNetwork": "100% covered"
          }},
          {{
            "section": "Optical",
            "title": "Optical Coverage",
            "description": "not covered",
            "notes": [],
            "coverage_network": "",
            "coverage_nonNetwork": ""
          }},
          {{
            "section": "Other Services",
            "title": "Teleconsultation healthcare services", 
            "description": "Through Service Providers Only",
            "notes": [],
            "coverage_network": "",
            "coverage_nonNetwork": ""
          }},
          {{
            "section": "Other Services",
            "title": "Second Medical Opinion through service provider only", 
            "description": "Through Service Providers Only",
            "notes": [],
            "coverage_network": "",
            "coverage_nonNetwork": ""
          }}
        ]
        ```
        
        ---
        **Now, process the entire text provided below and return the complete JSON object.**
        **REMEMBER: Each distinct benefit MUST be its own separate JSON object. Never combine multiple benefits.**
        ---
        
        **Text to Parse:**
        ```
        {self.text}
        ```
        """
        return prompt


    def parse(self) -> List[Dict]:
        prompt = self._build_llm_prompt()
        
        messages = [
            {"role": "system", "content": "You are a data extraction expert that always returns a single, valid JSON object with a 'benefits' key as requested."},
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.chat_client.chat.completions.create(
                model=self.deployment_name,
                messages=messages,
                max_tokens=16000,
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            response_content = response.choices[0].message.content
            
            # The LLM should return a JSON object like {"benefits": [...]}
            data = json.loads(response_content)
            chunks = data.get("benefits", [])
            
            # Post-process each chunk to ensure footnotes are correctly mapped
            for chunk in chunks:
                # Get the raw text that contains potential superscripts
                raw_text = chunk.get("rawText", "")
                title = chunk.get("title", "")
                
                # If no rawText, construct from available fields
                if raw_text:
                    raw_text = "Benefit section:" + chunk.get("section", "") + ", benefit:" + title + " " + chunk.get("description", "")
                    if chunk.get("notes"):
                        if isinstance(chunk.get("notes"), list) and chunk.get("notes"):
                            raw_text += " " + " ".join(chunk.get("notes"))
                    if chunk.get("coverage_network"):
                        raw_text += " " + "Coverage: Network " + chunk.get("coverage_network")
                    if chunk.get("coverage_nonNetwork"):
                        raw_text += " " + "Non-Network " + chunk.get("coverage_nonNetwork")
                else:
                    raw_text = "Benefit section:" + chunk.get("section", "") + ", benefit:" + title + " " + chunk.get("description", "")
                    if chunk.get("notes"):
                        if isinstance(chunk.get("notes"), list) and chunk.get("notes"):
                            raw_text += " " + " ".join(chunk.get("notes"))
                    if chunk.get("coverage_network"):
                        raw_text += " " + "Coverage: Network " + chunk.get("coverage_network")
                    if chunk.get("coverage_nonNetwork"):
                        raw_text += " " + "Non-Network " + chunk.get("coverage_nonNetwork")
                
                chunk["rawText"] = raw_text
                
                # Use LLM notes directly (LLM is now instructed to only include relevant footnotes)
                notes = chunk.get("notes", [])
                if isinstance(notes, str):
                    notes = [notes] if notes else []
                
                chunk["notes"] = notes
                
                # Add metadata
                chunk["filename"] = self.filename
                chunk["blobUrl"] = self.document_url
                chunk["md5Hash"] = self.md5_hash
                chunk["orgId"] = self.org_id
            
            with open("output.json", "w") as f:
                json.dump(chunks, f, indent=2)
            print(f"Output written to output.json")
            return chunks

        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logging.error(f"Failed to parse LLM response: {e}")
            logging.error(f"LLM Response was: {response_content}")
            return []

        except Exception as e:
            logging.error(f"An unexpected error occurred during LLM parsing: {e}")
            return []
