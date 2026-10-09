MEDICINE_PRESCRIPTION_TRIGGER_SQL = {
    "medicines_patient_prescription_match_insert": """
        CREATE TRIGGER IF NOT EXISTS medicines_patient_prescription_match_insert
        BEFORE INSERT ON medicines
        FOR EACH ROW
        WHEN NEW.prescription_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM prescriptions p
            WHERE p.id = NEW.prescription_id
              AND p.patient_id = NEW.patient_id
          )
        BEGIN
          SELECT RAISE(ABORT, 'medicine prescription patient mismatch');
        END;
    """,
    "medicines_patient_prescription_match_update": """
        CREATE TRIGGER IF NOT EXISTS medicines_patient_prescription_match_update
        BEFORE UPDATE OF patient_id, prescription_id ON medicines
        FOR EACH ROW
        WHEN NEW.prescription_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM prescriptions p
            WHERE p.id = NEW.prescription_id
              AND p.patient_id = NEW.patient_id
          )
        BEGIN
          SELECT RAISE(ABORT, 'medicine prescription patient mismatch');
        END;
    """,
    "confirmed_prescription_medicines_insert": """
        CREATE TRIGGER IF NOT EXISTS confirmed_prescription_medicines_insert
        BEFORE INSERT ON medicines
        FOR EACH ROW
        WHEN NEW.prescription_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM prescriptions p
            WHERE p.id = NEW.prescription_id
              AND p.confirmed_at IS NOT NULL
          )
        BEGIN
          SELECT RAISE(ABORT, 'confirmed prescription medicines are immutable');
        END;
    """,
    "confirmed_prescription_medicines_update": """
        CREATE TRIGGER IF NOT EXISTS confirmed_prescription_medicines_update
        BEFORE UPDATE ON medicines
        FOR EACH ROW
        WHEN NEW.prescription_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM prescriptions p
            WHERE p.id = NEW.prescription_id
              AND p.confirmed_at IS NOT NULL
          )
        BEGIN
          SELECT RAISE(ABORT, 'confirmed prescription medicines are immutable');
        END;
    """,
    "confirmed_prescription_medicines_delete": """
        CREATE TRIGGER IF NOT EXISTS confirmed_prescription_medicines_delete
        BEFORE DELETE ON medicines
        FOR EACH ROW
        WHEN OLD.prescription_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM prescriptions p
            WHERE p.id = OLD.prescription_id
              AND p.confirmed_at IS NOT NULL
          )
        BEGIN
          SELECT RAISE(ABORT, 'confirmed prescription medicines are immutable');
        END;
    """,
}
