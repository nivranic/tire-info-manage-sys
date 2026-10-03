//! Python JSON integers are arbitrary precision; floats use binary64 semantics.
use std::cmp::Ordering;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct Magnitude(Vec<u32>);
impl Magnitude {
    fn decimal(digits: &str) -> Option<Self> {
        if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        let digits = digits.trim_start_matches('0');
        let mut limbs = Vec::new();
        for end in (1..=digits.len()).rev().step_by(9) {
            let start = end.saturating_sub(9);
            limbs.push(digits[start..end].parse().ok()?);
        }
        Some(Self(limbs))
    }
    fn from_u64(mut value: u64) -> Self {
        let mut limbs = Vec::new();
        while value != 0 {
            limbs.push((value % 1_000_000_000) as u32);
            value /= 1_000_000_000;
        }
        Self(limbs)
    }
    fn times_power_of_two(&mut self, bits: u32) {
        for _ in 0..bits {
            let mut carry = 0u64;
            for limb in &mut self.0 {
                let value = u64::from(*limb) * 2 + carry;
                *limb = (value % 1_000_000_000) as u32;
                carry = value / 1_000_000_000;
            }
            if carry != 0 {
                self.0.push(carry as u32);
            }
        }
    }
    fn cmp(&self, other: &Self) -> Ordering {
        self.0
            .len()
            .cmp(&other.0.len())
            .then_with(|| self.0.iter().rev().cmp(other.0.iter().rev()))
    }
}

#[derive(Clone, Debug)]
pub(super) enum Numeric {
    Integer {
        negative: bool,
        magnitude: Magnitude,
    },
    Float(f64),
}
impl Numeric {
    pub(super) fn parse(token: &str) -> Option<Self> {
        if token.contains(['.', 'e', 'E']) {
            let value: f64 = token.parse().ok()?;
            return value.is_finite().then_some(Self::Float(value));
        }
        let (negative, digits) = token
            .strip_prefix('-')
            .map_or((false, token), |digits| (true, digits));
        let magnitude = Magnitude::decimal(digits)?;
        Some(Self::Integer {
            negative: negative && !magnitude.0.is_empty(),
            magnitude,
        })
    }
    pub(super) fn cmp(&self, other: &Self) -> Ordering {
        match (self, other) {
            (
                Self::Integer {
                    negative: left_negative,
                    magnitude: left,
                },
                Self::Integer {
                    negative: right_negative,
                    magnitude: right,
                },
            ) => signed_cmp(*left_negative, *right_negative, left.cmp(right)),
            (Self::Float(left), Self::Float(right)) => {
                left.partial_cmp(right).expect("finite numeric")
            }
            (
                Self::Integer {
                    negative,
                    magnitude,
                },
                Self::Float(value),
            ) => integer_float_cmp(*negative, magnitude, *value),
            (Self::Float(_), Self::Integer { .. }) => other.cmp(self).reverse(),
        }
    }
}
fn signed_cmp(left_negative: bool, right_negative: bool, magnitude: Ordering) -> Ordering {
    match (left_negative, right_negative) {
        (true, false) => Ordering::Less,
        (false, true) => Ordering::Greater,
        (true, true) => magnitude.reverse(),
        (false, false) => magnitude,
    }
}
fn integer_float_cmp(negative: bool, magnitude: &Magnitude, float: f64) -> Ordering {
    if float == 0.0 {
        return signed_cmp(negative, false, magnitude.cmp(&Magnitude(Vec::new())));
    }
    let float_negative = float.is_sign_negative();
    if negative != float_negative {
        return if negative {
            Ordering::Less
        } else {
            Ordering::Greater
        };
    }
    // Every finite binary64 has fewer than 315 decimal digits. Avoid
    // multiplying an unbounded JSON integer by the subnormal denominator.
    if magnitude.0.len() > 35 {
        return if negative {
            Ordering::Less
        } else {
            Ordering::Greater
        };
    }
    let bits = float.abs().to_bits();
    let exponent = ((bits >> 52) & 0x7ff) as i32;
    let fraction = bits & ((1u64 << 52) - 1);
    let (mantissa, power) = if exponent == 0 {
        (fraction, -1074)
    } else {
        (fraction | (1u64 << 52), exponent - 1023 - 52)
    };
    let mut integer = magnitude.clone();
    let mut float_magnitude = Magnitude::from_u64(mantissa);
    if power >= 0 {
        float_magnitude.times_power_of_two(power as u32);
    } else {
        integer.times_power_of_two((-power) as u32);
    }
    signed_cmp(negative, float_negative, integer.cmp(&float_magnitude))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn number(token: &str) -> Numeric {
        Numeric::parse(token).unwrap()
    }
    #[test]
    fn arbitrary_integer_and_binary_float_comparison_is_lossless() {
        assert_eq!(
            number("9007199254740993").cmp(&number("9007199254740992.0")),
            Ordering::Greater
        );
        assert_eq!(
            number("18446744073709551616").cmp(&number("18446744073709551616.0")),
            Ordering::Equal
        );
        assert_eq!(
            number("18446744073709551617").cmp(&number("18446744073709551616.0")),
            Ordering::Greater
        );
        assert_eq!(
            number("-9007199254740993").cmp(&number("-9007199254740992.0")),
            Ordering::Less
        );
        assert_eq!(number("0").cmp(&number("-0.0")), Ordering::Equal);
        assert_eq!(number("2").cmp(&number("2.5")), Ordering::Less);
        assert_eq!(number("-2").cmp(&number("-2.5")), Ordering::Greater);
        assert_eq!(number("0").cmp(&number("5e-324")), Ordering::Less);
        assert_eq!(number("0").cmp(&number("-5e-324")), Ordering::Greater);
        assert!(Numeric::parse("1e309").is_none());
        assert_eq!(number("1e-10000").cmp(&number("0")), Ordering::Equal);
        let large = "9".repeat(500);
        assert_eq!(number(&large).cmp(&number("1e308")), Ordering::Greater);
    }
}
