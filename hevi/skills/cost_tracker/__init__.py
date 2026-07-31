"""
Cost Tracker Skill
Tracks and records costs for various production operations.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class CostTrackerSkill:
    """
    Cost Tracker Skill - tracks resource usage and costs for production operations.
    
    Input: Operation details and resource consumption
    Output: Cost calculation and recording
    """
    
    def __init__(self):
        # Cost rates per operation/resource type
        self.cost_rates = {
            "tts_per_char": 0.0001,      # $0.0001 per character
            "gpu_hour": 0.50,            # $0.50 per GPU hour
            "storage_gb_month": 0.023,   # $0.023 per GB per month (similar to AWS S3)
            "api_call": 0.0005,          # $0.0005 per API call
            "render_minute": 0.10,       # $0.10 per minute of video rendering
        }
        
        # Track operations
        self.operation_log = []
    
    async def execute(self, *, operation_type: str, resources_used: Dict[str, float], 
                     metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Calculate and record costs for an operation.
        
        Args:
            operation_type: Type of operation (tts, render, storage, etc.)
            resources_used: Dictionary of resources consumed
            metadata: Additional metadata about the operation
            
        Returns:
            Dictionary containing cost calculation and tracking info
        """
        try:
            # Calculate cost based on operation type and resources used
            calculated_cost = await self._calculate_cost(operation_type, resources_used)
            
            # Record the operation
            operation_record = {
                "timestamp": datetime.now().isoformat(),
                "operation_type": operation_type,
                "resources_used": resources_used,
                "calculated_cost": calculated_cost,
                "metadata": metadata or {}
            }
            
            self.operation_log.append(operation_record)
            
            # Log for monitoring
            logger.info(f"Operation cost recorded: {operation_type}, ${calculated_cost:.4f}")
            
            return {
                "status": "success",
                "operation_id": len(self.operation_log),  # Simple ID based on position
                "calculated_cost": calculated_cost,
                "resources_used": resources_used,
                "operation_type": operation_type,
                "timestamp": operation_record["timestamp"]
            }
            
        except Exception as e:
            logger.error(f"Cost tracking failed: {str(e)}")
            raise RuntimeError(f"Cost tracker skill failed: {str(e)}")
    
    async def _calculate_cost(self, operation_type: str, resources_used: Dict[str, float]) -> float:
        """Calculate cost based on operation type and resources."""
        total_cost = 0.0
        
        if operation_type == "tts":
            chars = resources_used.get("characters", 0)
            total_cost += chars * self.cost_rates["tts_per_char"]
        
        elif operation_type == "gpu_compute":
            hours = resources_used.get("gpu_hours", 0)
            total_cost += hours * self.cost_rates["gpu_hour"]
        
        elif operation_type == "storage":
            gb_months = resources_used.get("gb_months", 0)
            total_cost += gb_months * self.cost_rates["storage_gb_month"]
        
        elif operation_type == "api_call":
            count = resources_used.get("call_count", 0)
            total_cost += count * self.cost_rates["api_call"]
        
        elif operation_type == "render":
            minutes = resources_used.get("render_minutes", 0)
            total_cost += minutes * self.cost_rates["render_minute"]
        
        # For other operation types, we might have custom calculations
        # or just apply generic resource costs
        for resource, amount in resources_used.items():
            if resource in self.cost_rates and resource not in ["characters", "gpu_hours", "gb_months", "call_count", "render_minutes"]:
                total_cost += amount * self.cost_rates[resource]
        
        return round(total_cost, 6)  # Round to nearest $0.000001
    
    async def get_total_cost(self) -> float:
        """Get total cost across all operations."""
        return sum(op["calculated_cost"] for op in self.operation_log)
    
    async def get_operation_summary(self) -> Dict[str, Any]:
        """Get summary of all tracked operations."""
        if not self.operation_log:
            return {"total_operations": 0, "total_cost": 0.0}
        
        operation_types = {}
        total_cost = 0.0
        
        for op in self.operation_log:
            op_type = op["operation_type"]
            if op_type not in operation_types:
                operation_types[op_type] = {"count": 0, "total_cost": 0.0}
            
            operation_types[op_type]["count"] += 1
            operation_types[op_type]["total_cost"] += op["calculated_cost"]
            total_cost += op["calculated_cost"]
        
        return {
            "total_operations": len(self.operation_log),
            "total_cost": round(total_cost, 6),
            "by_type": operation_types,
            "operations": self.operation_log[-10:]  # Last 10 operations
        }


# Convenience function for direct execution
async def cost_tracker_skill_execute(*, operation_type: str, resources_used: Dict[str, float], 
                                  metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Direct execution function for the cost tracker skill.
    """
    skill = CostTrackerSkill()
    return await skill.execute(operation_type=operation_type, 
                             resources_used=resources_used, 
                             metadata=metadata)