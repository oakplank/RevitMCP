# -*- coding: utf-8 -*-
"""Revit Project Information Tool for RevitMCP."""

# Import common Revit API classes
# from Autodesk.Revit.DB import Document
# from Autodesk.Revit.ApplicationServices import Application

def get_project_information(doc, app):
    """Collects basic project information from the Revit document and application.

    Args:
        doc (Autodesk.Revit.DB.Document): The active Revit document.
        app (Autodesk.Revit.ApplicationServices.Application): The Revit application instance.

    Returns:
        dict: A dictionary containing project information.
    """
    if not doc:
        return {"error": "No active document found."}
    if not app:
        return {"error": "Revit application instance not found."}

    project_info = doc.ProjectInformation
    
    info_dict = {
        "project_name": project_info.Name,
        "project_file_path": doc.PathName,
        "revit_version": app.VersionName,
        "revit_build": app.VersionBuild,
        "project_number": project_info.Number,
        "client_name": project_info.ClientName,
        "project_status": project_info.Status,
        "project_address": project_info.Address,
        "project_issue_date": project_info.IssueDate,
        "organization_name": project_info.OrganizationName,
        "organization_description": project_info.OrganizationDescription
    }
    
    # For fields that might be empty or not set, provide a default or check
    for key, value in info_dict.items():
        if not value: # Covers None or empty strings
            info_dict[key] = "Not Set"
            
    return info_dict

if __name__ == '__main__':
    # This section is for testing outside of Revit, if possible,
    # or for direct execution within a Revit Python Shell environment.
    # You would need to mock 'doc' and 'app' or have a live Revit session.
    print("This script is intended to be called from within Revit.")
    # Example (mocked for testing - this won't run standalone):
    # class MockProjectInfo:
    #     Name = "Mock Project"
    #     Number = "MP001"
    #     IssueDate = "2023-01-01"
    #     ClientName = "Mock Client"
    #     Status = "In Progress"
    #     Address = "123 Mock St"
    #     OrganizationName = "Mock Org"
    #     OrganizationDescription = "A test organization"

    # class MockDoc:
    #     ProjectInformation = MockProjectInfo()
    #     PathName = "C:\\mock\\path\\project.rvt"

    # class MockApp:
    #     VersionName = "Revit Mock 2024"
    #     VersionBuild = "24.0.0.0"

    # mock_doc = MockDoc()
    # mock_app = MockApp()
    # print(get_project_information(mock_doc, mock_app)) 