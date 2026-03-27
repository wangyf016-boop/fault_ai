"""知识图谱构建管道"""
from .triple_generator import TripleGenerator
from .triple_to_kg_builder import TripleToKGBuilder

__all__ = ['TripleGenerator', 'TripleToKGBuilder']
