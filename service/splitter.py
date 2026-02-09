from typing import List, Tuple
from langchain_core.documents import Document as Chunk
import logging

class SuperRecursiveSplitter:
    """
    A class for recursively splitting text into chunks of a target size.

    This class implements a recursive splitting algorithm that divides text into chunks
    based on a list of separators, while attempting to maintain a target chunk size.

    Attributes:
        separators (List[str]): A list of string separators to use for splitting text.
        target_chunk_size (int): The desired size for each chunk of text.
        separator_placeholders (bool): If True, replace separators with placeholders.
        overlap (int): The number of characters to overlap between adjacent chunks.
        chunks (List[str]): The resulting list of text chunks after splitting.
        verbosity (int): Controls the verbosity of output (0 for no output, 1 for verbose output).

    """

    def __init__(self, separators: List[str], target_chunk_size: int, separator_placeholders: bool = True, overlap: int = 0, verbosity: int = 0, reconstruct: bool = True):
        """
        Initialize the DWRecursiveSplitter.

        Args:
            separators (List[str]): A list of string separators to use for splitting text.
            target_chunk_size (int): The desired size for each chunk of text.
            separator_placeholders (bool, optional): If True, replace separators with placeholders. Defaults to True.
            overlap (int, optional): The number of characters to overlap between adjacent chunks. Defaults to 0.
            verbosity (int, optional): Controls the verbosity of output (0 for no output, 1 for verbose output). Defaults to 0.
        """
        self.separators = separators
        self.target_chunk_size = target_chunk_size
        self.separator_placeholders = separator_placeholders
        self.overlap = abs(overlap)
        self.chunks = []
        self.verbosity = verbosity
        self.pages = []
        self.placeholder_map = {
            "\n\n": "~P", 
            "\n": "~L", 
            ".": "~D", 
            ",": "~C", 
            " ": "~S"
        }
        self.reconstruct = reconstruct
    
    def split_and_merge(self, parts: List[str], sep: str) -> List[str]:
        """
        Split the given parts using the specified separator and merge them back if possible.

        Args:
            parts (List[str]): The list of text parts to split and merge.
            sep (str): The separator to use for splitting.

        Returns:
            List[str]: A list of split and merged text parts.
        """
        placeholder = self.placeholder_map.get(sep, "~")
        new_parts = []
        for part in parts:
            sub_parts = part.split(sep)
            if self.verbosity == 1:
                print(f"\t\tSplitting this chunk resulted in {len(sub_parts)} sub-parts.")
            if self.separator_placeholders:
                if self.reconstruct:
                    sub_parts = [(sub_part + placeholder) if i < len(sub_parts) - 1 else sub_part for i, sub_part in enumerate(sub_parts)]
                else:
                    n_placeholders = len(sep)
                    sub_parts = [sub_part + (n_placeholders * "~") if i < len(sub_parts) - 1 else sub_part for i, sub_part in enumerate(sub_parts)]

            # Merging
            if self.verbosity == 1:
                print("\t\tScanning for sub parts that can be combined...")
            merged_sub_parts = []
            current_chunk = ""
            for sub_part in sub_parts:
                if len(sub_part) > self.target_chunk_size:
                    # If the sub_part itself is larger than the target size, add it as a separate chunk
                    if current_chunk:
                        merged_sub_parts.append(current_chunk)
                        current_chunk = ""
                    merged_sub_parts.append(sub_part)
                elif len(current_chunk) + len(sub_part) <= self.target_chunk_size:
                    current_chunk += sub_part
                else:
                    if current_chunk:
                        merged_sub_parts.append(current_chunk)
                    current_chunk = sub_part
            
            if current_chunk:
                merged_sub_parts.append(current_chunk)

            if self.verbosity == 1:
                print(f"\t\tAfter merging, we have {len(merged_sub_parts)} chunks.")
            new_parts.extend(merged_sub_parts)
            
        return new_parts
    
    def add_overlap(self, chunks: List[str]) -> List[str]:
        """
        Add overlap to the chunks based on the specified overlap size.

        Args:
            chunks (List[str]): The list of text chunks.

        Returns:
            List[str]: A list of text chunks with added overlap.
        """
        if self.overlap == 0:
            return chunks
        
        overlapped_chunks = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                overlapped_chunks.append(chunk + chunks[i+1][:self.overlap] if i+1 < len(chunks) else chunk)
            elif i == len(chunks) - 1:
                overlapped_chunks.append(chunks[i-1][-self.overlap:] + chunk)
            else:
                overlapped_chunks.append(chunks[i-1][-self.overlap:] + chunk + chunks[i+1][:self.overlap])
        
        return overlapped_chunks
    
    def split_into_chunks(self, text: str) -> List[str]:
        """
        Split the input text into chunks based on the specified separators and target chunk size.

        Args:
            text (str): The input text to be split into chunks.

        Returns:
            List[str]: A list of text chunks.
        """
        chunks = [text]
        if self.verbosity == 1:
            print("Beginning with 1 block of text, and split by each separator.")
        for sep_no, sep in enumerate(self.separators, start=1):
            escaped_sep = sep.replace('\n', '\\n')
            if self.verbosity == 1:
                print(rf"Separator #{sep_no}: '{escaped_sep}' (placeholder = {self.placeholder_map.get(sep, '~')})")
            new_chunks = []
            for cn, chunk in enumerate(chunks, start=1):
                if len(chunk) > self.target_chunk_size:
                    if self.verbosity == 1:
                        print(f"\tChunk {cn} has size ({len(chunk)}) > maximum chunk size ({self.target_chunk_size}).")
                    # Split only if the chunk is larger than the target size
                    sub_parts = self.split_and_merge([chunk], sep)
                    new_chunks.extend(sub_parts)
                    if self.verbosity == 1:
                        print("\n")
                else:
                    # If the chunk is already smaller, leave it as is
                    new_chunks.append(chunk)
                
            chunks = new_chunks
            if self.verbosity == 1:
                print(f"\tChunk splitting for this separator is complete. Total chunks now = {len(chunks)}")
            
            # Once all chunks are below or equal to the target size, stop splitting
            if all(len(chunk) <= self.target_chunk_size for chunk in chunks):
                if self.verbosity == 1:
                    print("All chunks are smaller than the maximum chunk size. Splitting is complete.")
                break
            elif self.verbosity == 1:
                print(f"{sum(len(chunk) <= self.target_chunk_size for chunk in chunks)}/{len(chunks)} chunks are smaller than the maximum chunk size. Continuing splitting.\n")
        
        
        final_chunks = []
        current_chunk = ""
        
        for chunk in chunks:
            if len(current_chunk) + len(chunk) <= self.target_chunk_size:
                # Combine chunks if they fit into the target chunk size
                current_chunk = current_chunk + " " + chunk if current_chunk else chunk
            else:
                # Otherwise, start a new chunk
                if current_chunk:
                    final_chunks.append(current_chunk)
                current_chunk = chunk
        
        # Add the last chunk if it's not empty
        if current_chunk:
            final_chunks.append(current_chunk)
            
        if self.verbosity == 1:
            print(f"FINAL NUMBER OF CHUNKS: {len(final_chunks)}")
        
        if self.reconstruct_original_text:
            reconstructed_chunks = [self.reconstruct_original_text(chunk) for chunk in final_chunks]
            final_chunks_with_overlap = self.add_overlap(reconstructed_chunks)
        else:
            final_chunks_with_overlap = self.add_overlap(final_chunks)
        
        self.chunks = final_chunks_with_overlap
        # print("\n\n")
        # for cn, chunk in enumerate(final_chunks_with_overlap):
        #     print(f"Original Chunk {cn+1} (length = {len(chunk)})")
        #     print(f"Original text:\n{chunk}\n\n")
        #     print(f"Processed Text {cn+1} (length = {len(self.reconstruct_original_text(chunk))})")
        #     print(f"Processed text:\n{self.reconstruct_original_text(chunk)}\n\n")
        
        return final_chunks_with_overlap
    
    def reconstruct_original_text(self, processed_text: str) -> str:
        """
        Reconstruct the original text by replacing placeholders with their corresponding separators.
        
        Args:
            processed_text (str): The text containing placeholders.
        
        Returns:
            str: The original text with separators restored.
        """
        for sep, placeholder in self.placeholder_map.items():
            processed_text = processed_text.replace(placeholder, sep)
        return processed_text


    def map_chunks_to_pages(self, pages_text: List[str]) -> List[List[int]]:
        """
        Map the chunks to their corresponding pages in the original text.

        Args:
            pages_text (List[str]): A list of strings, where each string represents a page of text.

        Returns:
            List[List[int]]: A list where each contains a list of page numbers that the chunk spans.
        """
        page_starts = [0]  # Track the starting index of each page in the concatenated text
        cumulative_length = 0
        for text in pages_text:
            cumulative_length += len(text)
            page_starts.append(cumulative_length)
        
        if self.verbosity == 1:
            print(f"{len(pages_text)} pages: {page_starts=}\n")
        chunk_page_map = []
        total_length = 0
        for cn, chunk in enumerate(self.chunks):
            if self.verbosity == 1:
                logging.info(f"MappingChunk {cn+1} (length = {len(chunk)})")
            # Calculate the actual start and end indices, accounting for overlap
            if cn == 0:
                start_idx = 0
            else:
                start_idx = total_length - self.overlap
            
            clean_chunk = chunk
            end_idx = start_idx + len(clean_chunk)
            
            if self.verbosity == 1:
                logging.info(f"\t{start_idx=}, {end_idx=}")
            
            # Find the start and end pages
            start_page = next((i for i, start in enumerate(page_starts) if start > start_idx), len(page_starts) - 1)
            end_page = next((i for i, start in enumerate(page_starts) if start > end_idx), len(page_starts) - 1)
            
            if self.verbosity == 1:
                logging.info(f"\t{start_page=}, {end_page=}")
            
            # Add the chunk and its page range to the map
            chunk_page_map.append(list(range(start_page, end_page + 1)))
            
            if cn == 0 or cn == len(self.chunks) - 1:
                total_length += len(clean_chunk) - self.overlap
            else:
                total_length += len(clean_chunk) - 2 * self.overlap

        self.pages = chunk_page_map
        
        return chunk_page_map
    
    def create_documents(self, additional_metadata: dict = None):
        """
        Create a list of Document objects from chunks and their corresponding page numbers.

        Args:
            additional_metadata (dict, optional): A dictionary where keys are metadata field names
                                                  and values are lists of metadata values.

        Returns:
            list: A list of Document objects with page content and metadata.

        Raises:
            ValueError: If the length of any additional_metadata value list doesn't match
                        the number of chunks.
        """
        documents = []
        num_chunks = len(self.chunks)

        if additional_metadata:
            for key, value_list in additional_metadata.items():
                if len(value_list) != num_chunks:
                    raise ValueError(f"Length of additional_metadata '{key}' ({len(value_list)}) "
                                     f"does not match the number of chunks ({num_chunks}).")

        for i, (chunk, page_numbers) in enumerate(zip(self.chunks, self.pages)):
            metadata = {"page_numbers": page_numbers}
            if additional_metadata:
                for key, value_list in additional_metadata.items():
                    metadata[key] = value_list[i]
            documents.append(Chunk(page_content=chunk, metadata=metadata))
        return documents