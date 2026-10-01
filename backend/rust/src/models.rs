use serde::{Deserialize, Serialize};

use crate::error::AppError;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LabeledValue {
    #[serde(default)]
    pub label: String,
    /// Missing counts as empty, so the row is dropped by validation (API-U1).
    #[serde(default)]
    pub value: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Address {
    pub label: String,
    pub street: String,
    pub city: String,
    pub region: String,
    pub postal_code: String,
    pub country: String,
}

impl Address {
    fn is_blank(&self) -> bool {
        [&self.street, &self.city, &self.region, &self.postal_code, &self.country]
            .iter()
            .all(|s| s.trim().is_empty())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tag {
    pub id: i64,
    pub name: String,
    pub color: String,
}

#[derive(Debug, Serialize)]
pub struct TagWithCount {
    #[serde(flatten)]
    pub tag: Tag,
    pub contact_count: i64,
}

#[derive(Debug, Deserialize)]
pub struct TagInput {
    pub name: String,
    #[serde(default)]
    pub color: Option<String>,
}

pub const TAG_COLORS: &[&str] =
    &["slate", "red", "orange", "amber", "green", "teal", "sky", "indigo", "violet", "pink"];

impl TagInput {
    pub fn validate(mut self) -> Result<Self, AppError> {
        self.name = self.name.trim().to_string();
        if self.name.is_empty() {
            return Err(AppError::Validation("tag name is required".into()));
        }
        if self.name.chars().count() > 40 {
            return Err(AppError::Validation("tag name must be 40 characters or fewer".into()));
        }
        if let Some(c) = &self.color
            && !TAG_COLORS.contains(&c.as_str()) {
                return Err(AppError::Validation(format!("unknown tag color '{c}'")));
            }
        Ok(self)
    }
}

/// A full contact, as returned by `GET /api/contacts/:id`.
#[derive(Debug, Serialize)]
pub struct Contact {
    pub id: i64,
    pub first_name: String,
    pub last_name: String,
    pub company: String,
    pub job_title: String,
    pub birthday: Option<String>,
    pub notes: String,
    pub favorite: bool,
    pub emails: Vec<LabeledValue>,
    pub phones: Vec<LabeledValue>,
    pub addresses: Vec<Address>,
    pub tags: Vec<Tag>,
    pub created_at: String,
    pub updated_at: String,
}

/// A row in the contact list.
#[derive(Debug, Serialize)]
pub struct ContactSummary {
    pub id: i64,
    pub first_name: String,
    pub last_name: String,
    pub company: String,
    pub job_title: String,
    pub favorite: bool,
    pub email: Option<String>,
    pub phone: Option<String>,
    pub tag_ids: Vec<i64>,
}

#[derive(Debug, Serialize)]
pub struct ContactPage {
    pub items: Vec<ContactSummary>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Serialize)]
pub struct LetterIndex {
    pub letter: String,
    /// Position of the letter's first contact in the sorted list.
    pub offset: i64,
    pub count: i64,
}

#[derive(Debug, Deserialize)]
pub struct ListQuery {
    pub q: Option<String>,
    pub tag: Option<i64>,
    pub favorite: Option<bool>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

/// Body for creating or replacing a contact.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct ContactInput {
    pub first_name: String,
    pub last_name: String,
    pub company: String,
    pub job_title: String,
    pub birthday: Option<String>,
    pub notes: String,
    pub favorite: bool,
    pub emails: Vec<LabeledValue>,
    pub phones: Vec<LabeledValue>,
    pub addresses: Vec<Address>,
    pub tag_ids: Vec<i64>,
}

impl ContactInput {
    /// Trim fields, drop empty rows, and reject obviously bad input.
    pub fn validate(mut self) -> Result<Self, AppError> {
        for s in [
            &mut self.first_name,
            &mut self.last_name,
            &mut self.company,
            &mut self.job_title,
            &mut self.notes,
        ] {
            *s = s.trim().to_string();
        }
        if self.first_name.is_empty() && self.last_name.is_empty() && self.company.is_empty() {
            return Err(AppError::Validation("a name or company is required".into()));
        }

        self.birthday = self.birthday.map(|b| b.trim().to_string()).filter(|b| !b.is_empty());
        if let Some(b) = &self.birthday
            && !is_iso_date(b) {
                return Err(AppError::Validation("birthday must be YYYY-MM-DD".into()));
            }

        for list in [&mut self.emails, &mut self.phones] {
            list.retain(|v| !v.value.trim().is_empty());
            for v in list.iter_mut() {
                v.value = v.value.trim().to_string();
                v.label = normalize_label(&v.label);
            }
        }
        for e in &self.emails {
            let valid = e.value.split_once('@').is_some_and(|(user, domain)| {
                !user.is_empty() && domain.contains('.') && !e.value.contains(char::is_whitespace)
            });
            if !valid {
                return Err(AppError::Validation(format!("'{}' is not a valid email", e.value)));
            }
        }

        self.addresses.retain(|a| !a.is_blank());
        for a in &mut self.addresses {
            a.label = normalize_label(&a.label);
            for s in [&mut a.street, &mut a.city, &mut a.region, &mut a.postal_code, &mut a.country]
            {
                *s = s.trim().to_string();
            }
        }

        self.tag_ids.sort_unstable();
        self.tag_ids.dedup();
        Ok(self)
    }
}

fn normalize_label(label: &str) -> String {
    let label = label.trim().to_lowercase();
    if label.is_empty() { "other".into() } else { label }
}

fn is_iso_date(s: &str) -> bool {
    let parts: Vec<&str> = s.split('-').collect();
    let [y, m, d] = parts.as_slice() else { return false };
    if y.len() != 4 || m.len() != 2 || d.len() != 2 {
        return false;
    }
    match (y.parse::<u32>(), m.parse::<u32>(), d.parse::<u32>()) {
        (Ok(_), Ok(m), Ok(d)) => (1..=12).contains(&m) && (1..=31).contains(&d),
        _ => false,
    }
}
